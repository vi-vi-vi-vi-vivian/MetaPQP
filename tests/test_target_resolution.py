from portal_audit.application.use_cases.run_page_audit import PageAuditPipeline
from portal_audit.domain.models import PageAuditRequest


def test_huawei_console_target_makes_chinese_locale_explicit():
    request = PageAuditRequest(
        url=(
            "https://console.huaweicloud.com/modelarts/"
            "?region=cn-southwest-2#/model-studio/resourcePlanManagement"
        ),
        product="tokenplan",
        page_id="purchase",
        locale="zh-CN",
    )

    target = PageAuditPipeline.target_for(request)

    assert target.page_id == "purchase"
    assert target.page_surface == "console"
    assert target.url == (
        "https://console.huaweicloud.com/modelarts/"
        "?region=cn-southwest-2&locale=zh-cn#/model-studio/resourcePlanManagement"
    )


def test_target_does_not_rewrite_non_console_url():
    request = PageAuditRequest(url="https://example.test/product", locale="zh-CN")

    target = PageAuditPipeline.target_for(request)

    assert target.url == request.url
    assert target.page_surface == "portal"


def test_missing_page_id_uses_readable_purchase_identity_from_console_url():
    request = PageAuditRequest(
        url=(
            "https://console.huaweicloud.com/agentarts/?region=cn-southwest-2"
            "#/shopping?product_list=%5B%7B%22skuCode%22%3A"
            "%22officeace.personal.package.standard%22%7D%5D"
        ),
        locale="en-US",
    )

    target = PageAuditPipeline.target_for(request)

    assert target.page_id == "officeace-purchase"
