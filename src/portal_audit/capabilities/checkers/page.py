"""Initial deterministic check catalog."""

from __future__ import annotations

from collections import Counter

import httpx

from portal_audit.domain.models import (
    CheckRun,
    CheckSpec,
    CheckStatus,
    ElementLocation,
    EvidenceElement,
    InteractiveElement,
    PageSnapshot,
)


def element_location(element: EvidenceElement) -> ElementLocation:
    return ElementLocation(
        element_ref=element.element_ref,
        selector=element.selector,
        tag=element.tag,
        text=element.text,
        href=element.href,
        bounds=element.bounds,
    )


def interactive_location(element: InteractiveElement) -> ElementLocation:
    return ElementLocation(
        element_ref=element.element_ref or "mobile-tap-target",
        selector=element.selector,
        tag=element.tag,
        text=element.text,
        href=element.href,
        bounds=element.bounds,
    )


class PageLoadChecker:
    id = "page-load-checker"

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        passed = (
            snapshot.http_status is not None
            and snapshot.http_status < 400
            and bool(snapshot.body_text.strip())
        )
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            title=spec.title,
            reason=f"final_url={snapshot.final_url}, status={snapshot.http_status}, body_chars={len(snapshot.body_text)}",
            severity=spec.default_severity,
            evidence=[snapshot.final_url, f"HTTP {snapshot.http_status}"],
            suggestion=None if passed else "修复页面加载、重定向或空白页问题。",
            executor_id=self.id,
        )


class DocumentStructureChecker:
    id = "document-structure-checker"

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        h1 = [item for item in snapshot.headings if item.get("level") == 1 and item.get("text")]
        passed = bool(snapshot.title.strip())
        locations = []
        if not passed:
            visual_heading = next(
                (
                    item
                    for item in snapshot.evidence_elements
                    if item.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
                ),
                None,
            )
            if visual_heading:
                locations.append(element_location(visual_heading))
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            title=spec.title,
            reason=(
                f"title={'present' if snapshot.title.strip() else 'missing'}, "
                f"observed_h1_count={len(h1)}"
            ),
            severity=spec.default_severity,
            evidence=[snapshot.title, *[item["text"] for item in h1]],
            locations=locations,
            suggestion=None if passed else "补充能够描述当前页面主题的非空 Title。",
            executor_id=self.id,
        )


class RuntimeErrorsChecker:
    id = "runtime-errors-checker"

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        actionable_network_errors = [
            item
            for item in snapshot.network_errors
            if "ERR_ABORTED" not in str(item.get("error", ""))
            and "networkidle timeout" not in str(item.get("error", ""))
        ]
        ignored_network_errors = len(snapshot.network_errors) - len(actionable_network_errors)
        confirmed_critical = [
            item for item in actionable_network_errors if item.get("resource_type") == "document"
        ]
        unverified = snapshot.console_errors + [
            str(item) for item in actionable_network_errors if item not in confirmed_critical
        ]
        status = (
            CheckStatus.FAIL
            if confirmed_critical
            else CheckStatus.NEEDS_VERIFICATION
            if unverified
            else CheckStatus.PASS
        )
        evidence = (
            [str(item) for item in confirmed_critical[:5]]
            if confirmed_critical
            else unverified[:10]
        )
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=status,
            title=spec.title,
            reason=(
                f"console_errors={len(snapshot.console_errors)}, "
                f"failed_requests={len(actionable_network_errors)}, "
                f"confirmed_critical={len(confirmed_critical)}, "
                f"unverified_runtime_signals={len(unverified)}, "
                f"ignored_aborted_or_idle={ignored_network_errors}"
            ),
            severity=spec.default_severity,
            evidence=evidence,
            suggestion=(
                "修复已确认失败的页面主文档请求。"
                if confirmed_critical
                else "确认 Console 错误或失败请求是否影响页面核心功能。"
                if unverified
                else None
            ),
            executor_id=self.id,
        )


class BrokenLinksChecker:
    id = "broken-links-checker"

    def __init__(self, max_links: int = 20):
        self.max_links = max_links

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        links = [
            item.href
            for item in snapshot.interactive_elements
            if item.href and item.href.startswith(("http://", "https://"))
        ]
        unique_links = list(Counter(links))[: self.max_links]
        broken: list[str] = []
        protected: list[str] = []
        unverified: list[str] = []
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            for url in unique_links:
                try:
                    response = await client.head(url)
                    if response.status_code in {403, 405, 418, 429}:
                        response = await client.get(url, headers={"Range": "bytes=0-0"})
                    if response.status_code in {401, 403, 418, 429}:
                        protected.append(f"{response.status_code} {url}")
                    elif response.status_code >= 400:
                        broken.append(f"{response.status_code} {url}")
                except httpx.HTTPError as exc:
                    unverified.append(f"unverified {url}: {type(exc).__name__}")
        status = (
            CheckStatus.FAIL
            if broken
            else CheckStatus.NEEDS_VERIFICATION
            if protected or unverified
            else CheckStatus.PASS
        )
        broken_urls = {
            item.split(" ", 1)[1]
            for item in broken
            if " " in item and item.split(" ", 1)[1].startswith(("http://", "https://"))
        }
        locations = [
            element_location(item)
            for item in snapshot.evidence_elements
            if item.href in broken_urls
        ][:10]
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=status,
            title=spec.title,
            reason=(
                f"checked_links={len(unique_links)}, broken_links={len(broken)}, "
                f"protected_or_rate_limited={len(protected)}, "
                f"unverified_links={len(unverified)}"
            ),
            severity=spec.default_severity,
            evidence=(broken if broken else protected + unverified)[:10],
            locations=locations,
            suggestion=(
                "修复或移除已确认失效的链接，并确认正确目标地址。"
                if broken
                else "在浏览器或具备相应权限的环境中重新验证这些链接。"
                if protected or unverified
                else None
            ),
            executor_id=self.id,
        )


class ImageAltChecker:
    id = "image-alt-checker"

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        images = [item for item in snapshot.evidence_elements if item.tag == "img"]
        missing = [item for item in images if item.has_alt is False]
        context_equivalent = [
            item for item in missing if item.accessible_name or item.surrounding_text
        ]
        confirmed_failures = [
            item
            for item in missing
            if item.interactive_ancestor and not item.accessible_name and not item.surrounding_text
        ]
        ambiguous = [
            item
            for item in missing
            if item not in context_equivalent and item not in confirmed_failures
        ]
        status = (
            CheckStatus.FAIL
            if confirmed_failures
            else CheckStatus.NEEDS_VERIFICATION
            if ambiguous
            else CheckStatus.PASS
        )
        evidence_items = confirmed_failures if confirmed_failures else ambiguous
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=status,
            title=spec.title,
            reason=(
                f"visible_images={len(images)}, missing_alt={len(missing)}, "
                f"equivalent_context={len(context_equivalent)}, "
                f"confirmed_unnamed_image_controls={len(confirmed_failures)}, "
                f"ambiguous_images={len(ambiguous)}"
            ),
            severity=spec.default_severity,
            evidence=[item.selector or item.element_ref for item in evidence_items[:10]],
            locations=[element_location(item) for item in evidence_items[:10]],
            suggestion=(
                "为无可访问名称的图像控件补充准确名称。"
                if confirmed_failures
                else "确认图片用途：信息图片提供等价文本，装饰图片使用空 Alt。"
                if ambiguous
                else None
            ),
            executor_id=self.id,
        )


class MobileHorizontalOverflowChecker:
    id = "mobile-horizontal-overflow-checker"

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        layout = snapshot.mobile_layout
        if layout is None:
            return CheckRun(
                check_spec_id=spec.id,
                check_spec_version=spec.version,
                status=CheckStatus.NEEDS_VERIFICATION,
                title=spec.title,
                reason="mobile layout evidence is unavailable",
                severity=spec.default_severity,
                confidence=0,
                suggestion="使用完整 Mobile 设备模拟重新采集页面布局证据。",
                executor_id=self.id,
            )

        overflow = layout.overflow_elements
        unlocated_overflow = (
            layout.document_scroll_width > layout.viewport_width + 1 and not overflow
        )
        status = (
            CheckStatus.FAIL
            if overflow
            else CheckStatus.NEEDS_VERIFICATION
            if unlocated_overflow
            else CheckStatus.PASS
        )
        evidence = [
            (
                f"viewport_width={layout.viewport_width}, "
                f"document_scroll_width={layout.document_scroll_width}"
            ),
            *[
                (
                    f"{item.selector or item.element_ref}: "
                    f"x={item.bounds.get('x', 0):.1f}, "
                    f"width={item.bounds.get('width', 0):.1f}"
                )
                for item in overflow[:10]
                if item.bounds
            ],
        ]
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=status,
            title=spec.title,
            reason=(
                f"viewport_width={layout.viewport_width}, "
                f"document_scroll_width={layout.document_scroll_width}, "
                f"unexpected_overflow_elements={len(overflow)}"
            ),
            severity=spec.default_severity,
            evidence=evidence,
            locations=overflow[:10],
            suggestion=(
                "约束超宽容器、图片或长文本，并保留轮播等明确横向手势区域。"
                if status != CheckStatus.PASS
                else None
            ),
            executor_id=self.id,
        )


class MobileTapTargetChecker:
    id = "mobile-tap-target-checker"
    minimum_css_px = 24
    recommended_css_px = 44
    control_tags = ("button", "input", "select", "textarea")
    control_roles = ("button", "tab", "checkbox", "radio", "switch")

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        if snapshot.mobile_layout is None:
            return CheckRun(
                check_spec_id=spec.id,
                check_spec_version=spec.version,
                status=CheckStatus.NEEDS_VERIFICATION,
                title=spec.title,
                reason="mobile touch evidence is unavailable",
                severity=spec.default_severity,
                confidence=0,
                suggestion="使用带触控模拟的 Mobile 浏览器上下文重新采集。",
                executor_id=self.id,
            )

        candidates = [
            item
            for item in snapshot.interactive_elements
            if item.enabled and item.bounds and self._is_control(item)
        ]
        violations = [item for item in candidates if self._below_minimum(item)]
        below_recommended = [
            item
            for item in candidates
            if float(item.bounds.get("width", 0)) < self.recommended_css_px
            or float(item.bounds.get("height", 0)) < self.recommended_css_px
        ]
        return CheckRun(
            check_spec_id=spec.id,
            check_spec_version=spec.version,
            status=CheckStatus.FAIL if violations else CheckStatus.PASS,
            title=spec.title,
            reason=(
                f"meaningful_controls={len(candidates)}, "
                f"below_24px={len(violations)}, "
                f"below_recommended_44px={len(below_recommended)}"
            ),
            severity=spec.default_severity,
            evidence=[
                (
                    f"{item.text or item.selector or item.element_ref}: "
                    f"{item.bounds.get('width', 0):.1f}x"
                    f"{item.bounds.get('height', 0):.1f}px"
                )
                for item in violations[:10]
            ],
            locations=[interactive_location(item) for item in violations[:10]],
            suggestion=(
                "将关键控件触控区域扩展到至少 24×24 CSS px，优先达到 44×44 CSS px。"
                if violations
                else None
            ),
            executor_id=self.id,
        )

    def _is_control(self, item: InteractiveElement) -> bool:
        if item.tag in self.control_tags or (item.role or "") in self.control_roles:
            return True
        if item.tag != "a" or not item.bounds:
            return False
        width = float(item.bounds.get("width", 0))
        height = float(item.bounds.get("height", 0))
        return not item.text.strip() or (
            width < self.minimum_css_px and height < self.minimum_css_px
        )

    def _below_minimum(self, item: InteractiveElement) -> bool:
        assert item.bounds is not None
        width = float(item.bounds.get("width", 0))
        height = float(item.bounds.get("height", 0))
        if item.tag == "a" and item.tag not in self.control_tags and not item.role:
            return width < self.minimum_css_px and height < self.minimum_css_px
        return width < self.minimum_css_px or height < self.minimum_css_px
