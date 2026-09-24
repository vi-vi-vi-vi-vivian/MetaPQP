from unittest.mock import AsyncMock, Mock

from portal_audit.adapters.browser.content_scope import (
    CONSOLE_CHROME_SELECTOR,
    primary_content_root,
    projected_content_text,
)
from portal_audit.domain.models import PageSurface


def _collection(*items):
    collection = Mock()
    collection.count = AsyncMock(return_value=len(items))
    collection.nth.side_effect = list(items)
    return collection


async def test_console_content_prefers_routed_purchase_region_over_document_body():
    body = Mock()
    body.first = body
    purchase = Mock()
    purchase.inner_text = AsyncMock(
        return_value="购买 Token Plan 个人版套餐\n购买时长\n包月\n一个月\n应付金额 ¥9.90"
    )
    page = Mock()

    def locate(selector):
        if selector == "html > body":
            return body
        if selector == "ti-app-layout-main":
            return _collection(purchase)
        return _collection()

    page.locator.side_effect = locate

    root = await primary_content_root(page, PageSurface.CONSOLE)

    assert root is purchase


async def test_console_content_uses_custom_element_app_root_when_needed():
    body = Mock()
    body.first = body
    app_root = Mock()
    app_root.inner_text = AsyncMock(
        return_value="OfficeAce 套餐购买\n套餐配置\n标准版\n购买时长\n1年"
    )
    page = Mock()

    def locate(selector):
        if selector == "html > body":
            return body
        if selector == "body > root":
            return _collection(app_root)
        return _collection()

    page.locator.side_effect = locate

    root = await primary_content_root(page, "console")

    assert root is app_root


async def test_portal_content_keeps_the_document_body_unchanged():
    body = Mock()
    body.first = body
    body.inner_text = AsyncMock(return_value="Portal product page")
    page = Mock()
    page.locator.return_value = body

    root = await primary_content_root(page, PageSurface.PORTAL)
    text = await projected_content_text(root, PageSurface.PORTAL, timeout_ms=12_000)

    assert root is body
    assert text == "Portal product page"
    body.inner_text.assert_awaited_once_with(timeout=12_000)


async def test_console_text_projection_excludes_known_global_shell_regions():
    root = Mock()
    root.evaluate = AsyncMock(return_value="购买 Token Plan 个人版套餐\n应付金额 ¥9.90")

    text = await projected_content_text(root, "console", timeout_ms=12_000)

    assert text == "购买 Token Plan 个人版套餐\n应付金额 ¥9.90"
    call = root.evaluate.await_args
    assert call.args[1] == CONSOLE_CHROME_SELECTOR
    assert "cf-service-wrapper" in call.args[1]
    assert call.kwargs["timeout"] == 12_000
