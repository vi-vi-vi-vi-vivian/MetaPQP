from portal_audit.capabilities.context_detectors.detectors import (
    CommerceFeatureDetector,
    JourneyStageDetector,
    PageArchetypeDetector,
)
from portal_audit.domain.models import PageSnapshot


def test_product_landing_is_not_misclassified_by_unsubscribe_copy():
    snapshot = PageSnapshot(
        page_id="tokenplan",
        requested_url="https://www.huaweicloud.com/agentorchard/tokenplan.html",
        final_url="https://www.huaweicloud.com/agentorchard/tokenplan.html",
        title="Token Plan-智果园-华为云",
        body_text="产品优势 立即订阅。退订规则请参考服务说明。",
        viewport={"width": 1440, "height": 1000},
    )

    observation = JourneyStageDetector().detect(snapshot)[0]

    assert observation.value == "awareness"
    assert "立即订阅" in observation.evidence


def test_console_token_plan_purchase_page_has_purchase_stage_and_features():
    snapshot = PageSnapshot(
        page_id="purchase",
        requested_url="https://console.huaweicloud.com/modelarts/",
        final_url=(
            "https://console.huaweicloud.com/modelarts/"
            "?region=cn-southwest-2#/model-studio/resourcePlanManagement"
        ),
        title="MaaS - Console",
        body_text=(
            "Subscribe to Token Plan for Efficient Development. "
            "Lite ¥59.00 /month. Restocking at 10:00. 我的订单"
        ),
        viewport={"width": 1440, "height": 1000},
    )

    stage = JourneyStageDetector().detect(snapshot)[0]
    archetype = PageArchetypeDetector().detect(snapshot)[0]
    features = {item.value for item in CommerceFeatureDetector().detect(snapshot)}

    assert stage.value == "purchase"
    assert archetype.value == "product_landing"
    assert {"pricing", "purchase_entry"} <= features
