"""Conservative Playwright baseline collector adapter."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
from portal_audit.adapters.browser.content_scope import (
    primary_content_root,
    projected_content_text,
)
from portal_audit.adapters.browser.launcher import launch_chromium
from portal_audit.adapters.browser.visual_evidence import VisualEvidenceBuilder
from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.domain.models import (
    ActionRecord,
    ArtifactRef,
    AuthenticationSummary,
    AuthStatus,
    ElementLocation,
    EvidenceElement,
    InteractionTrace,
    InteractiveElement,
    MobileLayoutEvidence,
    PageSnapshot,
    PageSurface,
    PageTarget,
    TransitionTrace,
)

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
# Console micro-frontends may select a different bundle or route implementation
# for the default HeadlessChrome fingerprint.  Desktop audits represent a normal
# desktop-browser visit, so use the matching desktop identity for Console only.
# This does not bypass login or security challenges; those are still detected by
# the auth provider and stop the audit as before.
CONSOLE_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
DISCLOSURE_LABEL_PATTERN = re.compile(r"详情|计费|说明|规则|查看")


class PlaywrightBrowser:
    def __init__(
        self,
        store: LocalArtifactStore,
        *,
        headless: bool = True,
        timeout_ms: int = 60_000,
        visual_audit_enabled: bool = True,
        visual_audit_max_tiles: int | None = None,
        auth_provider=None,
    ):
        self.store = store
        self.auth_provider = auth_provider
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.visual_audit_enabled = visual_audit_enabled
        self.visual_evidence_builder = VisualEvidenceBuilder(max_tiles=visual_audit_max_tiles)

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
            browser = await launch_chromium(
                playwright.chromium,
                headless=self.headless,
                args=(
                    ["--disable-blink-features=AutomationControlled"]
                    if target.page_surface.value == "console"
                    else None
                ),
            )
            context_options = self._context_options(
                target,
                viewport,
                auth_session,
            )
            context = await browser.new_context(**context_options)
            if target.page_surface.value == "console":
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            document_responses: list[int] = []

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
            page.on(
                "response",
                lambda response: (
                    document_responses.append(response.status)
                    if response.request.is_navigation_request()
                    and response.frame == page.main_frame
                    else None
                ),
            )

            response = await self._navigate(page, target.url, network_errors)
            # A cached Console storage state can look structurally valid while
            # its server-side session has expired.  In that case the target
            # redirects this *same* context to Huawei Cloud's login page.
            # Complete the permitted password-login flow there, then revisit
            # the original target.  This avoids silently auditing a login
            # page under ``--auth auto``.
            effective_auth_session, recovery_response = (
                await self._resume_baseline_login_if_redirected(
                    page, target, auth_session, network_errors
                )
            )
            if recovery_response is not None:
                response = recovery_response
            if response is not None:
                document_status = response.status
            elif document_responses:
                document_status = document_responses[-1]
            await self._wait_for_network_idle(page, network_errors)

            # Console shells can become network-idle before their routed
            # micro-frontend has rendered. Wait for meaningful page content,
            # rather than treating the global service menu as the page.
            readiness = (
                await self._wait_for_interaction_content(page)
                if target.page_surface.value == "console"
                else {"ready": True}
            )
            if self._should_retry_console_route(target, readiness, console_errors):
                # AgentArts occasionally throws while parsing a hash-route on a
                # cold, isolated context.  Initialising the Console shell first
                # matches normal browser navigation without reusing a user's
                # profile or weakening the evidence gate.
                errors_before_recovery = len(console_errors)
                shell_url = self._console_shell_url(target.url)
                await self._navigate(page, shell_url, network_errors)
                await page.wait_for_timeout(1_200)
                recovery_url = self._console_json_closing_bracket_padding_url(target.url)
                response = await self._navigate(page, recovery_url, network_errors)
                if response is not None:
                    document_status = response.status
                elif document_responses:
                    document_status = document_responses[-1]
                await self._wait_for_network_idle(page, network_errors)
                readiness = await self._wait_for_interaction_content(page)
                if readiness["ready"]:
                    # The initial parse error belongs to the recovered cold
                    # route, not to the final captured page.
                    del console_errors[:errors_before_recovery]
            title = await page.title()
            content_root = await self._content_root(page, target.page_surface)
            body_text = await projected_content_text(
                content_root, target.page_surface, timeout_ms=self.timeout_ms
            )
            # Browser form controls can reflect a password into their DOM
            # ``value`` attribute.  Page HTML is an audit artifact and must
            # never persist a credential, even when capture stops on login.
            html = self._redact_html_credentials(await page.content())
            elements = await content_root.locator(
                "h1, h2, h3, h4, h5, h6, p, li, div, dt, dd, label, a, button, input, "
                "select, textarea, img, summary, [onclick], [tabindex], [role=link], "
                "[role=combobox], [role=checkbox], [role=radio], [role=switch], "
                "[aria-expanded], [aria-haspopup], [role=button], [role=tab], [role=alert]"
            ).evaluate_all(
                """els => {
                    const cssPath = (element) => {
                        if (element.id) return `#${CSS.escape(element.id)}`;
                        const parts = [];
                        let current = element;
                        while (current && current.nodeType === Node.ELEMENT_NODE) {
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
                            'a,button,input,select,textarea,summary,[onclick],[tabindex]:not([tabindex="-1"]),' +
                            '[role=link],[role=combobox],[role=checkbox],[role=radio],[role=switch],' +
                            '[aria-expanded],[aria-haspopup],[role=button],[role=tab]';
                        return els.map((e, index) => {
                        const rect = e.getBoundingClientRect();
                        const style = getComputedStyle(e);
                            // Keep elements that appear anywhere in the vertical document so
                            // a full-page capture remains useful, but exclude carousel slides
                            // and off-canvas content that cannot exist in the captured image.
                            // `display`/`visibility` alone reports those elements as visible.
                            const visible = rect.width > 0 && rect.height > 0 &&
                                rect.right > 0 && rect.left < document.documentElement.clientWidth &&
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
                            let parentText = e.parentElement
                                ? (e.parentElement.innerText || '').trim()
                                : '';
                            for (let node = e.parentElement, depth = 0; node && depth < 6; node = node.parentElement, depth++) {
                                const heading = node.querySelector('h1,h2,h3,h4,h5,h6,[class*="title"]');
                                const context = (node.innerText || '').trim();
                                if (heading && !e.contains(heading) && context.length < 1200) {
                                    parentText = context;
                                    break;
                                }
                            }
                            const icon = e.querySelector('img');
                            const iconName = icon ? (icon.alt || (icon.currentSrc || icon.src || '').split('/').pop().split('?')[0]) : '';
                            const classTokens = [...e.classList];
                            const optionClass = classTokens.find(token =>
                                /(?:^|[-_])(card|option|choice|plan|duration|month|spec)(?:$|[-_])/i.test(token)
                                || /^(card|option|choice|plan|duration|month|spec)/i.test(token)
                            );
                            let configurationGroup = null;
                            let configurationGroupNode = null;
                            let peerCount = 0;
                            if (optionClass && ['DIV', 'LI'].includes(e.tagName)
                                    && style.cursor === 'pointer' && !e.querySelector(interactiveSelector)) {
                                for (let node = e.parentElement, depth = 0; node && depth < 4; node = node.parentElement, depth++) {
                                    const peers = [...node.querySelectorAll(`.${CSS.escape(optionClass)}`)].filter(candidate => {
                                        const candidateStyle = getComputedStyle(candidate);
                                        const candidateRect = candidate.getBoundingClientRect();
                                        return candidateStyle.cursor === 'pointer' && candidateRect.width > 0 && candidateRect.height > 0;
                                    });
                                    if (peers.length >= 2 && peers.length <= 30) {
                                        configurationGroup = cssPath(node);
                                        configurationGroupNode = node;
                                        peerCount = peers.length;
                                        break;
                                    }
                                }
                            }
                            const rawText = (e.innerText || '').trim();
                            const optionNode = e.querySelector('[class~="title"], :scope > span, :scope > label');
                            const optionText = (optionNode?.innerText || rawText.split('\\n')[0] || '')
                                .trim().replace(/\\s+/g, ' ');
                            let nestedOptionAncestor = false;
                            for (let node = e.parentElement; node && node !== configurationGroupNode; node = node.parentElement) {
                                const ancestorLooksLikeOption = [...node.classList].some(token =>
                                    /(?:^|[-_])(card|option|choice|plan|duration|month|spec)(?:$|[-_])/i.test(token)
                                    || /^(card|option|choice|plan|duration|month|spec)/i.test(token)
                                );
                                if (ancestorLooksLikeOption && getComputedStyle(node).cursor === 'pointer') {
                                    nestedOptionAncestor = true;
                                    break;
                                }
                            }
                            const configurationControl = Boolean(
                                configurationGroup && peerCount >= 2 && optionText
                                && rawText.length <= 800 && !nestedOptionAncestor
                            );
                        return {
                            element_ref: `dom-${index + 1}`,
                            tag: e.tagName.toLowerCase(),
                            role: e.getAttribute('role'),
                            aria_expanded: e.getAttribute('aria-expanded'),
                            aria_controls: e.getAttribute('aria-controls'),
                            has_click_handler: e.hasAttribute('onclick') || typeof e.onclick === 'function',
                            image_only: Boolean(icon) && !(e.innerText || '').trim(),
                            text: (e.innerText || e.getAttribute('aria-label') ||
                                e.getAttribute('alt') || e.getAttribute('placeholder') ||
                                e.value || e.getAttribute('title') || labelledBy ||
                                (iconName ? `图片控件（资源名：${iconName}）` : '')).trim().replace(/\\s+/g, ' '),
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
                            ).trim().replace(/\\s+/g, ' '),
                            surrounding_text: parentText.replace(/\\s+/g, ' '),
                            interactive_ancestor: Boolean(interactiveAncestor),
                            page_region: (() => {
                                // Product audits deliberately exclude shared chrome. Console
                                // shells often use generic divs rather than semantic nav/header
                                // landmarks, so inspect their stable structural identifiers too.
                                const globalNavigation = e.closest(
                                    'nav,aside,[role=navigation],[role=menubar],#J_header,' +
                                    '[id^="cf_"],[id^="cf-"],[class*="modules-header" i],' +
                                    '[class*="service-list" i],[class*="global-service" i],' +
                                    '[class*="cf-header" i],[class*="cf-service" i]'
                                );
                                if (globalNavigation) return 'navigation';
                                const landmark = e.closest(
                                    'body > header, body > footer, [role=banner], [role=contentinfo], ' +
                                    '#header, #footer, .site-header, .site-footer, .global-header, .global-footer, ' +
                                    'body > [class*="footer" i]:not(main):not(article), body > .header-container'
                                );
                                if (!landmark) return 'content';
                                return landmark.matches('footer, [role=contentinfo], #footer, .site-footer, .global-footer, [class*="footer" i]')
                                    ? 'footer' : 'header';
                            })(),
                            enabled: !e.disabled && e.getAttribute('aria-disabled') !== 'true',
                            client_width: e.clientWidth,
                            scroll_width: e.scrollWidth,
                            client_height: e.clientHeight,
                            scroll_height: e.scrollHeight,
                            computed_style: {
                                overflow_x: style.overflowX,
                                overflow_y: style.overflowY,
                                text_overflow: style.textOverflow,
                                white_space: style.whiteSpace,
                                webkit_line_clamp: style.webkitLineClamp,
                                position: style.position,
                                z_index: style.zIndex
                            },
                            image_complete: e.tagName.toLowerCase() === 'img' ? e.complete : null,
                            natural_width: e.tagName.toLowerCase() === 'img' ? e.naturalWidth : null,
                            natural_height: e.tagName.toLowerCase() === 'img' ? e.naturalHeight : null,
                            current_src: e.tagName.toLowerCase() === 'img' ? e.currentSrc : null,
                            interactive: e.matches(interactiveSelector) || configurationControl,
                            configuration_control: configurationControl,
                            configuration_group: configurationControl ? configurationGroup : null,
                            configuration_option: configurationControl ? optionText : null,
                            selection_selected: configurationControl
                                ? classTokens.some(token => /^(checked|selected|active|current)$/i.test(token))
                                    || e.getAttribute('aria-selected') === 'true'
                                    || e.getAttribute('aria-checked') === 'true'
                                : null,
                            visible,
                            keep: e.tagName !== 'DIV' || configurationControl || e.matches(interactiveSelector)
                        };
                    }).filter(item => item.visible && item.keep);
                }"""
            )
            if target.page_surface.value == "console":
                elements = [
                    item
                    for item in elements
                    if item.get("page_region") not in {"header", "footer", "navigation"}
                ]
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
                            "page_region",
                            "aria_expanded",
                            "aria_controls",
                            "has_click_handler",
                            "image_only",
                            "configuration_group",
                            "configuration_option",
                            "selection_selected",
                        }
                    }
                )
                for item in elements
                if item["interactive"]
            ]
            document_size = await page.evaluate(
                """() => ({
                    width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
                    height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
                })"""
            )
            run_dir = self.store.run_dir(run_id)
            screenshot_path = run_dir / "screenshots" / "page-full.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            # Capture the undisturbed page before opening any information dialog.
            await page.screenshot(path=str(screenshot_path), full_page=True)
            viewport_path = run_dir / "screenshots" / "page-viewport.png"
            await page.screenshot(path=str(viewport_path), full_page=False)
            segment_artifacts = await _capture_page_segments(
                page, run_dir / "screenshots", viewport, document_size
            )
            disclosure_artifacts: list[ArtifactRef] = []

            async def capture_disclosure(label: str) -> None:
                path = run_dir / "screenshots" / f"information-disclosure-{len(disclosure_artifacts) + 1}.png"
                await page.screenshot(path=str(path), full_page=False)
                disclosure_artifacts.append(
                    ArtifactRef(
                        kind="interaction_screenshot", path=str(path), media_type="image/png",
                        metadata={"state": "information_disclosure", "label": label},
                    )
                )

            disclosed = await self._collect_disclosed_links(
                page, final_url, on_disclosure_opened=capture_disclosure
            )
            link_probe_results = await _probe_disclosed_links(page, disclosed)
            interactive.extend(disclosed)
            evidence_elements.extend(
                EvidenceElement(
                    element_ref=f"disclosed-{index}", tag="a", text=item.text,
                    href=item.href, selector=item.selector, bounds=item.bounds,
                    accessible_name=item.text, interactive_ancestor=True,
                )
                for index, item in enumerate(disclosed, start=1)
            )
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
            mobile_layout = (
                await self._collect_mobile_layout(page, viewport)
                if target.device == "mobile"
                else None
            )

            artifacts = [
                self.store.write_text(run_id, "artifacts/page.html", html, "text/html"),
                self.store.write_json(
                    run_id,
                    "artifacts/interactions.json",
                    [item.model_dump() for item in interactive],
                ),
                self.store.write_json(
                    run_id,
                    "artifacts/disclosed-links.json",
                    [item.model_dump() for item in disclosed],
                ),
                self.store.write_json(
                    run_id,
                    "artifacts/link-probes.json",
                    link_probe_results,
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
            artifacts.extend(segment_artifacts)
            artifacts.extend(disclosure_artifacts)
            if (
                self.visual_audit_enabled
                and target.device == "mobile"
                and target.page_surface == PageSurface.PORTAL
            ):
                artifacts.extend(
                    self.visual_evidence_builder.build(
                        full_page_path=screenshot_path,
                        viewport_path=viewport_path,
                        document_size=document_size,
                        output_dir=screenshot_path.parent,
                    )
                )
            snapshot = PageSnapshot(
                page_id=target.page_id,
                requested_url=target.url,
                final_url=final_url,
                title=title,
                http_status=document_status,
                viewport=viewport,
                document_size=document_size,
                body_text=body_text,
                headings=headings,
                interactive_elements=interactive,
                link_probe_results=link_probe_results,
                evidence_elements=evidence_elements,
                console_errors=console_errors,
                network_errors=network_errors,
                mobile_layout=mobile_layout,
                content_ready=readiness["ready"],
                artifacts=artifacts,
                authentication=(
                    effective_auth_session.summary
                    if effective_auth_session is not None
                    else auth_session.summary
                    if auth_session is not None
                    else AuthenticationSummary()
                ),
            )
            await context.close()
            await browser.close()
            return snapshot

    async def _resume_baseline_login_if_redirected(
        self,
        page,
        target: PageTarget,
        auth_session: BrowserAuthSession | None,
        network_errors: list[dict[str, str | int | None]],
    ) -> tuple[BrowserAuthSession | None, object | None]:
        """Refresh authentication only after an actual trusted login redirect.

        ``prepare`` validates cached state on a generic Console route.  Some
        product routes can nevertheless reject that state later.  We must not
        treat that redirect as anonymous page content: the configured provider
        can safely submit credentials only on its own login origin.
        """
        provider = self.auth_provider
        continue_login = getattr(provider, "continue_password_login", None)
        is_login_url = getattr(provider, "_is_login_url", None)
        if (
            provider is None
            or not callable(continue_login)
            or not callable(is_login_url)
            or not is_login_url(page.url)
        ):
            return auth_session, None

        refreshed = await continue_login(page)
        if refreshed.summary.status != AuthStatus.AUTHENTICATED:
            return refreshed, None
        return refreshed, await self._navigate(page, target.url, network_errors)

    @staticmethod
    def _redact_html_credentials(html: str) -> str:
        """Strip values from password controls before writing diagnostic HTML."""
        return re.sub(
            r"(<input\b[^>]*\btype\s*=\s*['\"]password['\"][^>]*\bvalue\s*=\s*)(['\"]).*?\2",
            r'\1\2[REDACTED]\2',
            html,
            flags=re.IGNORECASE,
        )

    async def inspect_interactions(
        self, target, run_id, candidates, auth_session=None
    ) -> list[InteractionTrace]:
        """Execute each allowed candidate in a fresh page, never sharing UI state."""
        viewport = {"width": 1440, "height": 1000} if target.device == "desktop" else {"width": 390, "height": 844}
        traces: list[InteractionTrace] = []
        async with async_playwright() as playwright:
            browser = await launch_chromium(
                playwright.chromium,
                headless=self.headless,
                args=(
                    ["--disable-blink-features=AutomationControlled"]
                    if target.page_surface.value == "console"
                    else None
                ),
            )
            try:
                for candidate in candidates:
                    paused_reason = None
                    element = candidate.element
                    action = ActionRecord(
                        action_id=candidate.candidate_id,
                        action_type="click",
                        risk_level=candidate.risk_level,
                        status="skipped" if candidate.execution_decision != "allowed" else "authorized",
                        safety_decision=candidate.execution_decision,
                        element_role=element.role,
                        element_name=element.text,
                        element_text=element.text,
                        element_href=element.href,
                        reason=candidate.decision_reason,
                    )
                    before = PageSnapshot(page_id=target.page_id, requested_url=target.url, final_url=target.url,
                        title="", viewport=viewport)
                    if candidate.execution_decision != "allowed":
                        action.status = 'skipped'
                        traces.append(InteractionTrace(candidate=candidate, before_snapshot=before,
                            trace=TransitionTrace(transition_id=candidate.candidate_id, transition_version="1.0.0",
                                from_node_id=target.page_id, to_node_id="dynamic", start_snapshot_id=before.snapshot_id,
                                start_url=target.url, action=action, safe_stop="authentication_required" if paused_reason else "not_executed", status="paused" if paused_reason else "skipped",
                                termination_reason=paused_reason or candidate.decision_reason)))
                        continue
                    context = await browser.new_context(**self._context_options(target, viewport, auth_session))
                    if target.page_surface.value == "console":
                        await context.add_init_script(
                            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                        )
                    page = await context.new_page()
                    page.set_default_timeout(self.timeout_ms)
                    console_errors: list[str] = []
                    page.on(
                        "console",
                        lambda message, captured_errors=console_errors: (
                            captured_errors.append(message.text)
                            if message.type == "error"
                            else None
                        ),
                    )
                    after = None
                    popups = []
                    try:
                        # A failed external destination must not consume the
                        # entire Page workflow budget.  This is deliberately
                        # shorter than normal baseline navigation and each
                        # candidate still records its own failure trace.
                        await page.goto(
                            target.url,
                            wait_until="domcontentloaded",
                            timeout=min(self.timeout_ms, 15_000),
                        )
                        await page.wait_for_timeout(600)
                        if (
                            target.page_surface.value == "console"
                            and self._has_console_route_parse_error(console_errors)
                        ):
                            await page.goto(
                                self._console_shell_url(target.url),
                                wait_until="domcontentloaded",
                                timeout=min(self.timeout_ms, 15_000),
                            )
                            await page.wait_for_timeout(1_200)
                            await page.goto(
                                self._console_json_closing_bracket_padding_url(target.url),
                                wait_until="domcontentloaded",
                                timeout=min(self.timeout_ms, 15_000),
                            )
                            await page.wait_for_timeout(1_200)
                        # The isolated interaction page is a fresh SPA load.  Do
                        # not resolve baseline selectors until its content has
                        # reached the same readiness threshold as the baseline.
                        await self._wait_for_interaction_content(page)
                        steps = candidate.configuration_steps or [element]
                        locator = await self._interaction_locator(page, steps[0], 0)
                        await locator.scroll_into_view_if_needed(timeout=5_000)
                        try:
                            control_bounds = await locator.bounding_box()
                        except (PlaywrightError, TypeError):
                            control_bounds = None
                        before_path = self.store.run_dir(run_id) / "screenshots" / f"interaction-{candidate.candidate_id}-before.png"
                        before_path.parent.mkdir(parents=True, exist_ok=True)
                        await page.screenshot(path=str(before_path), full_page=False)
                        before_content_root = await self._content_root(page, target.page_surface)
                        before = PageSnapshot(page_id=target.page_id, requested_url=target.url, final_url=page.url,
                            title=await page.title(), viewport=viewport,
                            body_text=await projected_content_text(
                                before_content_root, target.page_surface, timeout_ms=self.timeout_ms
                            ),
                            interaction_state=await self._control_state(locator),
                            quote_state=(await self._quote_state(page))
                            if candidate.kind == "quote_configuration" else {},
                            artifacts=[ArtifactRef(
                                kind="interaction_before_screenshot", path=str(before_path), media_type="image/png",
                                metadata={"control_bounds": control_bounds} if control_bounds else {},
                            )])
                        # Playwright attaches wrapper metadata to callbacks;
                        # built-in bound methods such as list.append cannot hold it.
                        page.on("popup", lambda popup, captured_popups=popups: captured_popups.append(popup))
                        for step_index, step in enumerate(steps):
                            # Resolve after each click because a reactive purchase
                            # form can replace the remaining card nodes.
                            step_locator = await self._interaction_locator(page, step, step_index)
                            await step_locator.scroll_into_view_if_needed(timeout=5_000)
                            await step_locator.click(no_wait_after=True, timeout=5_000)
                            await page.wait_for_timeout(350)
                        await page.wait_for_timeout(1_200)
                        result_page = popups[-1] if popups else page
                        if result_page is not page:
                            await result_page.wait_for_load_state("domcontentloaded", timeout=15_000)
                        # A DOMContentLoaded event can precede SPA/iframe content by seconds.
                        readiness = await self._wait_for_interaction_content(result_page)
                        authentication = None
                        if self.auth_provider:
                            if await self.auth_provider.requires_challenge(result_page):
                                paused_reason = await self._challenge_reason(result_page)
                            elif self.auth_provider._is_login_url(result_page.url):
                                authentication = await self.auth_provider.continue_password_login(result_page, persist=False)
                                if authentication.summary.status != AuthStatus.AUTHENTICATED:
                                    paused_reason = (
                                        '本条交互已暂停：登录需要滑块、短信验证码或其他安全验证，未继续操作。'
                                        if authentication.summary.status == AuthStatus.CHALLENGE_REQUIRED
                                        else '本条交互已暂停：账号密码登录未完成，未继续操作。'
                                    )
                                else:
                                    readiness = await self._wait_for_interaction_content(result_page)
                        screenshot = self.store.run_dir(run_id) / "screenshots" / f"interaction-{candidate.candidate_id}-after.png"
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        await result_page.screenshot(path=str(screenshot), full_page=False)
                        quote_state = (
                            await self._quote_state(result_page)
                            if candidate.kind == "quote_configuration" else {}
                        )
                        quote_state["requested_options"] = [
                            step.configuration_option or step.text for step in steps
                        ] if candidate.kind == "quote_configuration" else []
                        quote_state["requested_option_details"] = [
                            step.text for step in steps if step.text
                        ] if candidate.kind == "quote_configuration" else []
                        after_content_root = await self._content_root(result_page, target.page_surface)
                        after = PageSnapshot(page_id=target.page_id, requested_url=target.url, final_url=result_page.url,
                            title=await result_page.title(), viewport=viewport,
                            body_text=await projected_content_text(
                                after_content_root, target.page_surface, timeout_ms=self.timeout_ms
                            ),
                            content_ready=readiness['ready'],
                            interaction_state=await self._control_state(locator) if result_page is page and page.url == before.final_url else {},
                            quote_state=quote_state,
                            artifacts=[ArtifactRef(kind="interaction_screenshot", path=str(screenshot), media_type="image/png")])
                        if authentication:
                            after.authentication = authentication.summary
                        action.status = "completed"
                        outcome, reason = ('paused', paused_reason) if paused_reason else ('completed', '账号密码登录成功，已继续到结果页面' if authentication else '安全交互已执行')
                    except (PlaywrightError, PlaywrightTimeoutError) as error:
                        action.status = "error"
                        detail = " ".join(str(error).split())[:500]
                        suffix = f"：{detail}" if detail else ""
                        outcome, reason = "error", f"交互执行失败：{type(error).__name__}{suffix}"
                    finally:
                        for popup in popups:
                            await popup.close()
                        await page.close()
                        await context.close()
                    traces.append(InteractionTrace(candidate=candidate, before_snapshot=before, after_snapshot=after,
                        trace=TransitionTrace(transition_id=candidate.candidate_id, transition_version="1.0.0",
                            from_node_id=target.page_id, to_node_id="dynamic", start_snapshot_id=before.snapshot_id,
                            end_snapshot_id=after.snapshot_id if after else None, start_url=before.final_url,
                            end_url=after.final_url if after else None, action=action, safe_stop="authentication_required" if paused_reason else "interaction_observed",
                            status=outcome, termination_reason=reason)))
            finally:
                await browser.close()
        return traces

    @staticmethod
    async def _interaction_locator(page, step: InteractiveElement, index: int):
        """Resolve configuration cards semantically on each fresh SPA render."""
        if not step.configuration_option:
            locator = page.locator(step.selector)
            count = await locator.count()
            if count != 1:
                raise PlaywrightError(f"交互选择器未唯一匹配控件（匹配数：{count}）")
            return locator

        marker = f"metapqp-config-{index}"
        result = await page.locator("div,li").evaluate_all(
            """(els, request) => {
                const clean = value => (value || '').trim().replace(/\\s+/g, ' ');
                const visible = e => {
                    const rect = e.getBoundingClientRect();
                    const style = getComputedStyle(e);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none' && style.visibility !== 'hidden';
                };
                const looksLikeOption = e => [...e.classList].some(token =>
                    /(?:^|[-_])(card|option|choice|plan|duration|month|spec)(?:$|[-_])/i.test(token)
                    || /^(card|option|choice|plan|duration|month|spec)/i.test(token)
                );
                const optionText = e => {
                    const node = e.querySelector('[class~="title"], :scope > span, :scope > label');
                    return clean(node?.innerText || (e.innerText || '').split('\\n')[0]);
                };
                const candidates = els.filter(e => visible(e) && looksLikeOption(e)
                    && getComputedStyle(e).cursor === 'pointer'
                    && optionText(e).localeCompare(request.option, undefined, {sensitivity:'accent'}) === 0);
                const outermost = candidates.filter(e =>
                    !candidates.some(other => other !== e && other.contains(e))
                );
                if (outermost.length === 1) {
                    outermost[0].setAttribute('data-metapqp-config-target', request.marker);
                }
                return {count: outermost.length, candidates: candidates.length};
            }""",
            {"option": step.configuration_option, "marker": marker},
        )
        count = result.get("count", 0) if isinstance(result, dict) else 0
        if count != 1:
            raise PlaywrightError(
                f"配置项“{step.configuration_option}”未唯一匹配（匹配数：{count}）"
            )
        return page.locator(f'[data-metapqp-config-target="{marker}"]')

    @staticmethod
    async def _control_state(locator) -> dict:
        state = await locator.evaluate("""e => {
            const target = document.getElementById(e.getAttribute('aria-controls'));
            const visible = node => !!node && node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden';
            const classSelected = [...e.classList].some(token => /^(checked|selected|active|current)$/i.test(token));
            const configurationControl = [...e.classList].some(token =>
                /(?:^|[-_])(card|option|choice|plan|duration|month|spec)(?:$|[-_])/i.test(token)
                || /^(card|option|choice|plan|duration|month|spec)/i.test(token));
            return {expanded:e.getAttribute('aria-expanded'),
                selected:e.getAttribute('aria-selected') ?? (configurationControl ? classSelected : null),
                selection_control:configurationControl,
                checked: e.matches('input') ? e.checked : e.getAttribute('aria-checked'),
                open:e.tagName === 'SUMMARY' ? e.parentElement.open : null,
                panel_visible:target ? visible(target) : null,
                panel_text:visible(target) ? target.innerText : ''};
        }""")
        return state if isinstance(state, dict) else {}

    @staticmethod
    async def _quote_state(page) -> dict:
        """Extract a product-neutral quote projection from a purchase form."""
        state = await page.evaluate("""() => {
            const visible = e => !!e && e.getClientRects().length > 0
                && getComputedStyle(e).display !== 'none'
                && getComputedStyle(e).visibility !== 'hidden';
            const chrome = 'header,footer,nav,aside,[role=navigation],[role=menubar],#J_header,' +
                '[id^="cf_"],[id^="cf-"],[class*="modules-header" i],[class*="service-list" i],' +
                '[class*="global-service" i],[class*="cf-header" i],[class*="cf-service" i]';
            const clean = value => (value || '').trim().replace(/\\s+/g, ' ');
            const selected = [...document.querySelectorAll(
                '[aria-selected="true"],[aria-checked="true"],input:checked,.checked,.selected,.active,.current,' +
                '[class~="tp-selectitem-checked"],[class~="ti3-active"]'
            )].filter(e => visible(e) && !e.closest(chrome)).map(e => clean(e.innerText || e.value))
                .filter(value => value && value.length <= 800);
            const summary = {};
            [...document.querySelectorAll('label,dt')].filter(e => visible(e) && !e.closest(chrome)).forEach(label => {
                const key = clean(label.innerText);
                if (!key || key.length > 40) return;
                const parentText = clean(label.parentElement?.innerText);
                const siblingText = clean(label.nextElementSibling?.innerText);
                const value = siblingText || clean(parentText.replace(key, ''));
                if (value && value !== key && value.length <= 120) summary[key] = value;
            });
            const text = document.body?.innerText || '';
            const fixedSummaryFields = [
                ['购买时长', /(?:购买时长|Purchase Duration)\\s*[：:]?\\s*([^\\n]{1,80})/i],
                ['计费模式', /(?:计费模式|Billing Mode)\\s*[：:]?\\s*([^\\n]{1,80})/i],
            ];
            fixedSummaryFields.forEach(([key, pattern]) => {
                const match = text.match(pattern);
                if (!summary[key] && match) summary[key] = clean(match[1]);
            });
            const totalPattern = /(?:配置费用|应付(?:金额)?|总计|合计|订单金额|实付(?:金额)?|configuration fee|amount due|total|order amount)\\s*[：:]?\\s*([¥￥$])?\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)/i;
            const totalMatch = text.match(
                /(?:配置费用|应付(?:金额)?|总计|合计|订单金额|实付(?:金额)?|configuration fee|amount due|total|order amount)\\s*[：:]?\\s*([¥￥$])?\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)/i
            );
            const priceRegion = [...document.querySelectorAll('section,aside,form,div')]
                .filter(e => visible(e) && totalPattern.test(clean(e.innerText))
                    && clean(e.innerText).length <= 2500)
                .sort((a, b) => clean(a.innerText).length - clean(b.innerText).length)[0];
            const pricingText = [
                ...selected,
                ...Object.entries(summary).map(([key, value]) => `${key} ${value}`),
                clean(priceRegion?.innerText),
            ].join(' ');
            const simpleComplexities = [
                '税费', '附加费', '阶梯计价', '按量计费',
                'tax', 'surcharge', 'tiered pricing', 'pay as you go'
            ].filter(term => pricingText.toLocaleLowerCase().includes(term.toLocaleLowerCase()));
            const couponApplied = /(?:优惠券|代金券)[^。；\\n]{0,40}(?:已使用|抵扣|优惠|减免|[-−]\\s*[¥￥]?\\s*\\d)|(?:coupon|voucher)[^.;\\n]{0,40}(?:applied|discount|redeemed|[-−]\\s*[¥$]?\\s*\\d)/i
                .test(pricingText);
            const pricingComplexities = [
                ...simpleComplexities,
                ...(couponApplied ? ['优惠券抵扣'] : []),
            ];
            return {
                selected_options: [...new Set(selected)],
                summary,
                total: totalMatch ? totalMatch[2].replace(/,/g, '') : null,
                currency: totalMatch && totalMatch[1] === '$' ? 'USD' : totalMatch ? 'CNY' : null,
                total_label: totalMatch ? totalMatch[0] : null,
                pricing_complexities: pricingComplexities,
            };
        }""")
        return state if isinstance(state, dict) else {}

    async def _challenge_reason(self, page) -> str:
        text = (await self._primary_body(page).inner_text()).lower()
        if 'edgeone' in text or '连接安全性' in text:
            return '本条交互已暂停：本次自动化访问遇到站点连接安全检查（EdgeOne），尚未进入文档正文；这不是账号登录要求。'
        return '本条交互已暂停：页面出现额外安全验证，未继续操作；具体提示请查看结果截图。'

    async def _result_probe(self, page) -> dict:
        chunks, busy, content = [], False, 0
        for frame in page.frames:
            if frame != page.main_frame:
                owner = await frame.frame_element()
                if not await owner.is_visible():
                    continue
            probe = await frame.evaluate("""() => {
                const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
                const text = document.body?.innerText || '';
                const loading = [...document.querySelectorAll('[aria-busy=true],[role=progressbar],[class*=spinner],[class*=loading],[class*=skeleton]')]
                    .some(e => visible(e) && e.getBoundingClientRect().width > 10 && e.getBoundingClientRect().height > 10);
                const chrome = 'header,footer,nav,aside,[role=navigation],[role=menubar],#header,#footer,#J_header,' +
                    '[id^="cf_"],[id^="cf-"],[class*="modules-header" i],[class*="service-list" i],' +
                    '[class*="global-service" i],[class*="cf-header" i],[class*="cf-service" i]';
                const leaves = [...document.querySelectorAll('main *,[role=main] *,article *,body *')]
                    .filter(e => !e.children.length && visible(e) && !e.closest(chrome));
                return {text, busy:loading || /^(Loading\\.{0,3}|加载中[.…]*)$/mi.test(text),
                    content:leaves.map(e => e.innerText || '').join('').trim().length};
            }""")
            chunks.append(probe['text'])
            busy = busy or probe['busy']
            content += probe['content']
        return {'text': '\n'.join(chunks), 'busy': busy, 'content': content}

    async def _wait_for_interaction_content(self, page) -> dict:
        previous, stable = None, 0
        probe = {'text': '', 'busy': True, 'content': 0}
        # Bounded polling covers delayed SPA rendering and visible child frames.
        for _ in range(max(3, min(self.timeout_ms, 30_000) // 500)):
            try:
                probe = await self._result_probe(page)
                if self.auth_provider and self.auth_provider._is_login_url(page.url):
                    return {'text': probe['text'], 'ready': False}
                if self.auth_provider and await self.auth_provider.requires_challenge(page):
                    return {'text': probe['text'], 'ready': False}
                stable = stable + 1 if probe['text'] == previous else 0
                if stable >= 3 and not probe['busy'] and probe['content'] >= 40:
                    return {'text': probe['text'], 'ready': True}
                previous = probe['text']
            except PlaywrightError:
                stable = 0
            await page.wait_for_timeout(500)
        return {'text': probe['text'], 'ready': False}

    async def _collect_disclosed_links(
        self, page, base_url: str, *, on_disclosure_opened=None
    ) -> list[InteractiveElement]:
        return await collect_disclosed_links(
            page, base_url, on_disclosure_opened=on_disclosure_opened
        )

    @staticmethod
    async def _disclosure_candidates(page) -> list[tuple[str, str]]:
        """Return visible low-risk controls, including non-semantic click targets."""
        raw_candidates = await page.locator("*").evaluate_all(
            """els => {
                const cssPath = (element) => {
                    if (element.id) return `#${CSS.escape(element.id)}`;
                    const parts = [];
                    let current = element;
                    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 8) {
                        let part = current.tagName.toLowerCase();
                        const siblings = current.parentElement
                            ? Array.from(current.parentElement.children).filter(
                                sibling => sibling.tagName === current.tagName
                              )
                            : [];
                        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                        parts.unshift(part);
                        current = current.parentElement;
                    }
                    return parts.join(' > ');
                };
                const semanticSelector = 'a,button,[role=button],[role=link]';
                return els.map((element) => {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    const label = (element.innerText || element.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
                    const visible = rect.width > 0 && rect.height > 0 &&
                        rect.right > 0 && rect.left < document.documentElement.clientWidth &&
                        style.display !== 'none' && style.visibility !== 'hidden' &&
                        Number(style.opacity || 1) > 0;
                    const classSignalsInteraction = Array.from(element.classList).some(name =>
                        /(^|[-_])(link|click|action|trigger|toggle|expand)([-_]|$)/i.test(name)
                    );
                    const explicitlyClickable = element.matches(semanticSelector) ||
                        element.hasAttribute('onclick') || element.hasAttribute('tabindex') ||
                        style.cursor === 'pointer' || classSignalsInteraction;
                    return {selector: cssPath(element), label, visible, explicitlyClickable};
                }).filter(item => item.visible && item.explicitlyClickable &&
                    item.label.length > 0 && item.label.length <= 160);
            }"""
        )
        seen: set[tuple[str, str]] = set()
        candidates: list[tuple[str, str]] = []
        for item in raw_candidates:
            label = str(item["label"])
            selector = str(item["selector"])
            key = (selector, label)
            if not DISCLOSURE_LABEL_PATTERN.search(label) or key in seen:
                continue
            seen.add(key)
            candidates.append(key)
        return candidates

    @staticmethod
    async def _visible_http_links(page) -> list[dict]:
        return await page.locator("a[href]").evaluate_all("""els => els.map((e, index) => {
            const r=e.getBoundingClientRect(), s=getComputedStyle(e), href=e.href || '';
            return {href, text:(e.innerText||e.getAttribute('aria-label')||'').trim(),
              selector:`a[href]:nth-of-type(${index + 1})`,
              bounds:{x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height},
              visible:r.width>0&&r.height>0&&r.right>0&&r.left<document.documentElement.clientWidth&&s.display!=='none'&&s.visibility!=='hidden'};
        }).filter(x=>x.visible && /^https?:/i.test(x.href))""")

    async def _navigate(
        self,
        page,
        url: str,
        network_errors: list[dict[str, str | int | None]],
    ):
        try:
            return await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
        except PlaywrightTimeoutError as first_error:
            if await self._has_usable_document(page):
                network_errors.append(
                    {
                        "url": page.url,
                        "method": "DOCUMENT",
                        "error": (
                            "domcontentloaded timeout; baseline continued because body is usable"
                        ),
                    }
                )
                return None
            try:
                response = await page.goto(
                    url,
                    wait_until="commit",
                    timeout=min(self.timeout_ms, 30_000),
                )
            except PlaywrightTimeoutError:
                if await self._has_usable_document(page):
                    network_errors.append(
                        {
                            "url": page.url,
                            "method": "DOCUMENT",
                            "error": (
                                "navigation retry timeout; baseline continued because body is usable"
                            ),
                        }
                    )
                    return None
                raise first_error
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except PlaywrightTimeoutError:
                network_errors.append(
                    {
                        "url": page.url,
                        "method": "DOCUMENT",
                        "error": "domcontentloaded timeout after commit; baseline continued",
                    }
                )
            return response

    async def _wait_for_network_idle(
        self,
        page,
        network_errors: list[dict[str, str | int | None]],
    ) -> None:
        try:
            await page.wait_for_load_state(
                "networkidle", timeout=min(self.timeout_ms, 15_000)
            )
        except PlaywrightTimeoutError:
            network_errors.append(
                {
                    "url": page.url,
                    "method": "DOCUMENT",
                    "error": "networkidle timeout; baseline continued after DOMContentLoaded",
                }
            )

    @staticmethod
    def _console_shell_url(url: str) -> str:
        """Return the Console shell URL while preserving region and locale."""
        parsed = urlsplit(url)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )

    @staticmethod
    def _console_json_closing_bracket_padding_url(url: str) -> str:
        """Duplicate the ``product_list`` array closing bracket on recovery.

        AgentArts Console 26.8.4 removes one decoded ``]`` while constructing
        this hash route.  The recovery route therefore supplies two closing
        brackets: its defective path removes one and passes valid JSON onward.
        This is used only after observing that exact parser failure.
        """
        parsed = urlsplit(url)
        fragment = parsed.fragment
        match = re.search(r"([?&]product_list=)([^&]*)", fragment)
        if not match or match.group(2).endswith("%5D%5D"):
            return url
        padded_fragment = (
            fragment[: match.end(2)] + "%5D" + fragment[match.end(2) :]
        )
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, padded_fragment)
        )

    @staticmethod
    def _should_retry_console_route(
        target: PageTarget,
        readiness: dict,
        console_errors: list[str],
    ) -> bool:
        if target.page_surface.value != "console" or readiness.get("ready"):
            return False
        return PlaywrightBrowser._has_console_route_parse_error(console_errors)

    @staticmethod
    def _has_console_route_parse_error(console_errors: list[str]) -> bool:
        return any(
            "JSON.parse" in error and "Expected ',' or ']'" in error
            for error in console_errors
        )

    @staticmethod
    async def _has_usable_document(page) -> bool:
        try:
            body = PlaywrightBrowser._primary_body(page)
            return await body.count() > 0 and bool(
                (await body.inner_text(timeout=3_000)).strip()
            )
        except (PlaywrightError, PlaywrightTimeoutError):
            return False

    @staticmethod
    def _primary_body(page):
        """Select the document body, excluding invalid nested bodies from micro-frontends."""
        return page.locator("html > body").first

    async def _content_root(self, page, page_surface):
        """Keep portal behavior stable while scoping Console model evidence."""
        if getattr(page_surface, "value", page_surface) != "console":
            return self._primary_body(page)
        return await primary_content_root(page, page_surface)

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
        elif target.page_surface.value == "console":
            options["user_agent"] = CONSOLE_DESKTOP_USER_AGENT
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
                el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
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


async def collect_disclosed_links(
    page, base_url: str, *, on_disclosure_opened=None
) -> list[InteractiveElement]:
    """Discover links revealed by safe, same-page information disclosures.

    This is deliberately shared by standalone page capture and Journey capture:
    a link checker must receive the same evidence regardless of the scope that
    happened to collect the page.
    """
    candidates = await PlaywrightBrowser._disclosure_candidates(page)
    results: list[InteractiveElement] = []
    seen: set[str] = set()
    for selector, label in candidates:
        # Console micro-frontends can render duplicate selector paths.  Text is
        # the stable user-facing identity for an information disclosure; prefer
        # its visible instance over the first CSS match.
        by_text = page.get_by_text(label, exact=True)
        candidate = by_text.last if await by_text.count() else page.locator(selector).first
        try:
            await candidate.scroll_into_view_if_needed(timeout=3_000)
        except (PlaywrightError, PlaywrightTimeoutError):
            continue
        box = await candidate.bounding_box()
        scroll_y = await page.evaluate("window.scrollY")
        source_bounds = (
            {
                "x": float(box["x"]),
                "y": float(box["y"] + scroll_y),
                "width": float(box["width"]),
                "height": float(box["height"]),
            }
            if box
            else None
        )
        before_links = {
            item["href"] for item in await PlaywrightBrowser._visible_http_links(page)
        }
        before_disclosures = set(await PlaywrightBrowser._disclosure_candidates(page))
        try:
            # A footer disclosure can be partially covered by a fixed console
            # shell even after scroll-into-view.  The candidate has already
            # passed the low-risk disclosure filter, so a forced click here is
            # safer and more reliable than treating that overlay as evidence
            # that no disclosure exists.
            await candidate.click(timeout=3_000, force=True)
            await page.wait_for_timeout(800)
            if on_disclosure_opened is not None:
                await on_disclosure_opened(label)
            for item in await PlaywrightBrowser._visible_http_links(page):
                if item["href"] in before_links or item["href"] in seen:
                    continue
                seen.add(item["href"])
                results.append(
                    InteractiveElement(
                        element_ref=None,
                        tag="a",
                        text=f"{label} → {item['text']}",
                        href=urljoin(base_url, item["href"]),
                        selector=item["selector"],
                        bounds=item["bounds"],
                        enabled=True,
                    )
                )
            # Console shells commonly put an external-route warning in front
            # of a documentation link.  Its destination is rendered as text,
            # not as an anchor, and clicking "continue" is unnecessary (and
            # would cross the audit's confirmation boundary).  Collect the
            # displayed route directly so the normal link checker can verify
            # it without leaving the current page.
            for destination, destination_label in await _safe_warning_destinations(
                page, base_url
            ):
                if destination in seen:
                    continue
                seen.add(destination)
                results.append(
                    InteractiveElement(
                        element_ref=None,
                        tag="a",
                        text=f"{label} → {destination_label}",
                        href=destination,
                        selector=selector,
                        bounds=source_bounds,
                        enabled=True,
                    )
                )
            # Some console dialogs use a styled span or div for the final
            # documentation jump rather than an anchor.  Probe only controls
            # that become visible *after* a safe information disclosure and
            # whose label is itself informational; this cannot submit, buy,
            # configure, or otherwise mutate the account.
            revealed_controls = [
                item
                for item in await PlaywrightBrowser._disclosure_candidates(page)
                if item not in before_disclosures
            ]
            for revealed_selector, revealed_label in revealed_controls:
                revealed = page.locator(revealed_selector).first
                original_url = page.url
                pages_before = set(page.context.pages)
                try:
                    await revealed.click(timeout=3_000, force=True, no_wait_after=True)
                    await page.wait_for_timeout(800)
                    destinations = {page.url} if page.url != original_url else set()
                    destinations.update(
                        item.url
                        for item in page.context.pages
                        if item not in pages_before and item.url.startswith(("http://", "https://"))
                    )
                    for destination in destinations:
                        if destination in seen:
                            continue
                        seen.add(destination)
                        results.append(
                            InteractiveElement(
                                element_ref=None,
                                tag="a",
                                text=f"{label} → {revealed_label}",
                                href=destination,
                                selector=revealed_selector,
                                bounds=source_bounds,
                                enabled=True,
                            )
                        )
                finally:
                    for popup in [item for item in page.context.pages if item not in pages_before]:
                        try:
                            await popup.close()
                        except PlaywrightError:
                            pass
                    if page.url != original_url:
                        try:
                            await page.go_back(wait_until="domcontentloaded", timeout=5_000)
                        except (PlaywrightError, PlaywrightTimeoutError):
                            pass
        except (PlaywrightError, PlaywrightTimeoutError):
            pass
        finally:
            try:
                await page.keyboard.press("Escape")
            except PlaywrightError:
                pass
    return results


async def _capture_page_segments(
    page, screenshot_dir, viewport: dict[str, int], document_size: dict[str, int]
) -> list[ArtifactRef]:
    """Capture readable vertical page segments before interactive state changes."""
    scroll_target = await page.evaluate(
        """() => {
            const cssPath = element => {
                if (element.id) return `#${CSS.escape(element.id)}`;
                const parts = [];
                let current = element;
                while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 8) {
                    let part = current.tagName.toLowerCase();
                    const siblings = current.parentElement
                        ? Array.from(current.parentElement.children).filter(x => x.tagName === current.tagName)
                        : [];
                    if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                    parts.unshift(part);
                    current = current.parentElement;
                }
                return parts.join(' > ');
            };
            const isGlobalChrome = element => Boolean(element.closest(
                'header,footer,nav,aside,[role=navigation],[role=menubar],#J_header,' +
                '[id^="cf_"],[id^="cf-"],[class*="modules-header" i],' +
                '[class*="service-list" i],[class*="global-service" i],' +
                '[class*="cf-header" i],[class*="cf-service" i]'
            ));
            const candidates = Array.from(document.querySelectorAll('body *')).map(element => {
                const style = getComputedStyle(element), rect = element.getBoundingClientRect();
                return {element, style, rect, overflow: element.scrollHeight - element.clientHeight};
            }).filter(item => !isGlobalChrome(item.element) && item.overflow > 8 && item.rect.height > 160 &&
                ['auto', 'scroll'].includes(item.style.overflowY) && item.style.display !== 'none');
            const selected = candidates.sort((a, b) => b.overflow - a.overflow)[0];
            return selected ? {
                selector: cssPath(selected.element),
                scrollHeight: selected.element.scrollHeight,
                clientHeight: selected.element.clientHeight,
                initialTop: selected.element.scrollTop
            } : null;
        }"""
    )
    width = max(1, int(viewport["width"]))
    segment_height = max(1, int(viewport["height"]))
    page_height = max(
        segment_height,
        int((scroll_target or {}).get("scrollHeight") or document_size.get("height") or segment_height),
    )
    artifacts: list[ArtifactRef] = []
    for index, top in enumerate(range(0, page_height, segment_height), start=1):
        path = screenshot_dir / f"page-segment-{index}.png"
        # Console applications may render their main document in a nested
        # scroller, for which Playwright clip coordinates are not reliable.
        # Scrolling then taking a viewport image preserves what a user sees.
        if scroll_target:
            await page.locator(scroll_target["selector"]).evaluate(
                "(element, top) => { element.scrollTop = top; }", top
            )
        else:
            await page.evaluate("top => window.scrollTo(0, top)", top)
        await page.wait_for_timeout(120)
        actual_top = (
            await page.locator(scroll_target["selector"]).evaluate("element => element.scrollTop")
            if scroll_target else await page.evaluate("window.scrollY")
        )
        await page.screenshot(path=str(path), full_page=False)
        artifacts.append(
            ArtifactRef(
                kind="screenshot_segment", path=str(path), media_type="image/png",
                metadata={
                    "top": actual_top,
                    "width": width,
                    "height": segment_height,
                    "state": "base",
                    "scroll_container": bool(scroll_target),
                },
            )
        )
    if scroll_target:
        await page.locator(scroll_target["selector"]).evaluate(
            "(element, top) => { element.scrollTop = top; }", scroll_target["initialTop"]
        )
    else:
        await page.evaluate("window.scrollTo(0, 0)")
    return artifacts


async def _safe_warning_destinations(page, base_url: str) -> list[tuple[str, str]]:
    """Read displayed destinations from a console external-route warning.

    The route is evidence supplied by the page itself.  Reading it avoids a
    confirmation click while still allowing the deterministic link checker to
    test whether that advertised destination resolves.
    """
    values = await page.locator(
        "safe-warn-modal .app-safe-warn-url-color, "
        ".modal-class-safe-wrapper .app-safe-warn-url-color"
    ).evaluate_all(
        """els => els.map(element => {
            const dialog = element.closest('safe-warn-modal, .modal-class-safe-wrapper');
            const text = (dialog?.innerText || '').replace(/\\s+/g, ' ');
            return {
                value: (element.innerText || '').trim(),
                isExternalRouteWarning: /即将离开|third-party|external/i.test(text)
            };
        }).filter(item => item.isExternalRouteWarning && item.value)"""
    )
    destinations: list[tuple[str, str]] = []
    for item in values:
        value = str(item.get("value") or "").strip()
        resolved = urljoin(base_url, value)
        if resolved.startswith(("http://", "https://")):
            destinations.append((resolved, value))
    return destinations


async def _probe_disclosed_links(page, links: list[InteractiveElement]) -> list[dict]:
    """Verify disclosed destinations in the current authenticated browser context."""
    results: list[dict] = []
    for url in dict.fromkeys(item.href for item in links if item.href):
        try:
            response = await page.context.request.get(
                url,
                timeout=15_000,
                fail_on_status_code=False,
            )
            results.append({"url": url, "status": response.status, "source": "browser_context"})
        except PlaywrightError as error:
            results.append(
                {
                    "url": url,
                    "status": None,
                    "source": "browser_context",
                    "error": type(error).__name__,
                }
            )
    return results
