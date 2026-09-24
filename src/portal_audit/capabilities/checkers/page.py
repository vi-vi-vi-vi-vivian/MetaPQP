"""Initial deterministic check catalog."""

from __future__ import annotations

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
            and "domcontentloaded timeout" not in str(item.get("error", ""))
            and "navigation retry timeout" not in str(item.get("error", ""))
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

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        # Newly disclosed links are often the only route to billing, policy or
        # product detail. Check them before the initial page's navigation links.
        links = [
            item.href
            for item in sorted(snapshot.interactive_elements, key=lambda item: item.element_ref is not None)
            if item.href and item.href.startswith(("http://", "https://"))
        ]
        unique_links = list(dict.fromkeys(links))
        browser_probe_statuses = {
            str(item.get("url")): item.get("status")
            for item in snapshot.link_probe_results
            if item.get("url") and item.get("status") is not None
        }
        broken: list[str] = []
        protected: list[str] = []
        transient: list[str] = []
        unverified: list[str] = []
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            for url in unique_links:
                try:
                    browser_status = browser_probe_statuses.get(url)
                    if browser_status is not None:
                        status_code = int(browser_status)
                    else:
                        response = await client.head(url)
                        # HEAD is only an optimization. Some valid sites do not implement it
                        # consistently and return 4xx while a normal navigation succeeds.
                        if response.status_code >= 400:
                            response = await client.get(url, headers={"Range": "bytes=0-0"})
                        status_code = response.status_code
                    if status_code in {401, 403, 418, 429}:
                        protected.append(f"{status_code} {url}")
                    elif status_code >= 500:
                        transient.append(f"{status_code} {url}")
                    elif status_code >= 400:
                        broken.append(f"{status_code} {url}")
                except httpx.HTTPError as exc:
                    unverified.append(f"unverified {url}: {type(exc).__name__}")
        status = (
            CheckStatus.FAIL
            if broken
            else CheckStatus.NEEDS_VERIFICATION
            if protected or transient or unverified
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
                f"共检查 {len(unique_links)} 个不同链接，确认失效 {len(broken)} 个。"
                f"另有 {len(protected)} 个因访问权限或频率限制无法确认，"
                f"{len(transient)} 个遇到服务器暂时异常，{len(unverified)} 个因网络请求失败未完成验证。"
                + ("这些待确认链接不能直接认定为死链，需在浏览器中复查。" if protected or transient or unverified else "")
            ),
            severity=spec.default_severity,
            evidence=(broken if broken else protected + transient + unverified)[:10],
            locations=locations,
            suggestion=(
                "修复或移除已确认失效的链接，并确认正确目标地址。"
                if broken
                else "在浏览器或具备相应权限的环境中重新验证这些链接。"
                if protected or transient or unverified
                else None
            ),
            executor_id=self.id,
        )


class ImageAltChecker:
    id = "image-alt-checker"

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        # Global header/footer imagery belongs to shared-site accessibility
        # coverage, not a product Page audit.
        images = [
            item for item in snapshot.evidence_elements
            if item.tag == "img" and item.page_region not in {"header", "footer"}
        ]
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
                "如果这是可点击 Logo，为图片添加准确 Alt（如 alt=\"产品首页\"），"
                "或为父链接添加动作明确的 aria-label（如 aria-label=\"返回产品首页\"）；"
                "二者具备一个即可。其他图片控件按实际动作命名。"
                if confirmed_failures
                else "确认图片用途：信息图片提供等价文本，装饰图片使用空 Alt。"
                if ambiguous
                else None
            ),
            executor_id=self.id,
        )


class VisibleImageLoadFailureChecker:
    id = "visible-image-load-failure-checker"

    async def execute(self, spec: CheckSpec, snapshot: PageSnapshot) -> CheckRun:
        failed = [
            item for item in snapshot.evidence_elements
            if item.tag == "img" and item.image_complete is True and item.natural_width == 0
            and item.bounds and item.bounds.get("width", 0) > 0 and item.bounds.get("height", 0) > 0
        ]
        return CheckRun(
            check_spec_id=spec.id, check_spec_version=spec.version,
            status=CheckStatus.FAIL if failed else CheckStatus.PASS,
            title=spec.title,
            reason=(f"visible_images={len([x for x in snapshot.evidence_elements if x.tag == 'img'])}, "
                    f"confirmed_load_failures={len(failed)}"),
            severity=spec.default_severity,
            evidence=[f"{item.current_src or item.href or item.selector}: naturalWidth=0" for item in failed[:10]],
            locations=[element_location(item) for item in failed[:10]],
            suggestion="修复图片资源地址或发布配置；确认可见产品图、Logo 与图标在匿名及登录态下均可加载。" if failed else None,
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
