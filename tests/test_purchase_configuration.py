import ast
from pathlib import Path

from portal_audit.application.services.interaction_discovery import InteractionDiscovery
from portal_audit.capabilities.checkers.transition import (
    PriceCalculationConsistencyChecker,
    PurchaseSelectionStateConsistencyChecker,
)
from portal_audit.domain.models import (
    ActionRecord,
    ActionRiskLevel,
    InteractiveElement,
    PageSnapshot,
    TransitionTrace,
)
from portal_audit.domain.registry import CapabilityRegistry, CheckSpecRegistry, StandardsRegistry

ROOT = Path(__file__).parents[1]


def _registry():
    standards = StandardsRegistry(ROOT / "config/standards").load()
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    return CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()


def test_configuration_extraction_javascript_preserves_newline_escape():
    tree = ast.parse(
        (ROOT / "src/portal_audit/adapters/browser/playwright_browser.py").read_text(encoding="utf-8")
    )
    script = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "rawText.split" in node.value
    )
    assert "rawText.split('\\n')" in script


def test_quote_extraction_recognizes_fixed_cloud_purchase_selections():
    source = (
        ROOT / "src/portal_audit/adapters/browser/playwright_browser.py"
    ).read_text(encoding="utf-8")

    assert '[class~="tp-selectitem-checked"]' in source
    assert "购买时长|Purchase Duration" in source


def _trace(start: PageSnapshot, end: PageSnapshot) -> TransitionTrace:
    return TransitionTrace(
        transition_id="quote-scenario",
        transition_version="1.0.0",
        from_node_id="purchase",
        to_node_id="dynamic",
        start_snapshot_id=start.snapshot_id,
        end_snapshot_id=end.snapshot_id,
        start_url=start.final_url,
        end_url=end.final_url,
        action=ActionRecord(
            action_id="quote-scenario",
            action_type="click",
            risk_level=ActionRiskLevel.LOCAL_STATE,
            status="completed",
            safety_decision="allowed",
            element_name="个人高级版 · 连续包年",
        ),
        safe_stop="interaction_observed",
        status="completed",
        termination_reason="安全交互已执行",
    )


def test_configuration_groups_expand_to_full_cartesian_product():
    elements = []
    for group, options in (("plans", ["标准版", "高级版", "旗舰版"]),
                           ("durations", ["连续包年", "连续包月", "1个月"])):
        for index, option in enumerate(options):
            elements.append(InteractiveElement(
                tag="div", text=option, selector=f"#{group}-{index}",
                configuration_group=group, configuration_option=option,
                selection_selected=index == 0,
            ))
    snapshot = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000}, interactive_elements=elements,
    )
    candidates = InteractionDiscovery().discover(snapshot)
    assert len(candidates) == 9
    assert all(item.kind == "quote_configuration" for item in candidates)
    assert all(item.execution_decision == "allowed" for item in candidates)
    assert {tuple(step.configuration_option for step in item.configuration_steps) for item in candidates} == {
        (plan, duration)
        for plan in ("标准版", "高级版", "旗舰版")
        for duration in ("连续包年", "连续包月", "1个月")
    }


def test_configuration_groups_deduplicate_nested_card_and_card_body():
    elements = []
    for group, options in (("plans", ["标准版", "高级版", "旗舰版"]),
                           ("durations", ["连续包年", "连续包月"])):
        for index, option in enumerate(options):
            for suffix, selector in (("card", f"#{group}-{index}"),
                                     ("body", f"#{group}-{index} > .card-body")):
                elements.append(InteractiveElement(
                    tag="div", text=f"{option}-{suffix}", selector=selector,
                    configuration_group=group, configuration_option=option,
                    selection_selected=index == 0,
                ))
    snapshot = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000}, interactive_elements=elements,
    )

    candidates = InteractionDiscovery().discover(snapshot)

    assert len(candidates) == 6
    assert all(">" not in step.selector for item in candidates for step in item.configuration_steps)


def test_selection_and_price_checkers_pass_for_officeace_default_quote():
    start = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000},
    )
    end = start.model_copy(update={"quote_state": {
        "requested_options": ["个人高级版", "连续包年"],
        "selected_options": [
            "个人高级版 推荐 ￥198.00 /月 每月4,000积分",
            "连续包年 7折",
        ],
        "summary": {"规格": "个人高级版", "购买时长": "连续包年", "自动续费": "是"},
        "total": "1663.20",
        "currency": "CNY",
    }})
    trace = _trace(start, end)
    registry = _registry()
    selection = PurchaseSelectionStateConsistencyChecker().execute(
        registry.get("purchase-selection-state-consistency"), trace, start, end,
    )
    price = PriceCalculationConsistencyChecker().execute(
        registry.get("price-calculation-consistency"), trace, start, end,
    )
    assert selection.status == "pass"
    assert price.status == "pass"
    assert "¥198.00 × 12 × 0.7 = ¥1663.20" in price.reason


def test_price_checker_fails_a_material_mismatch_and_waits_on_hidden_factors():
    registry = _registry()
    spec = registry.get("price-calculation-consistency")
    start = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000},
    )
    mismatch = start.model_copy(update={"quote_state": {
        "requested_options": ["个人标准版", "3个月"],
        "selected_options": ["个人标准版 ￥98.00/月", "3个月"],
        "summary": {"规格": "个人标准版", "购买时长": "3个月"},
        "total": "300.00",
    }})
    missing = start.model_copy(update={"quote_state": {
        "requested_options": ["企业版", "按量"],
        "selected_options": ["企业版 阶梯计价"],
        "summary": {"规格": "企业版", "购买时长": "按量"},
        "total": "300.00",
        "pricing_complexities": ["阶梯计价"],
    }})
    failed = PriceCalculationConsistencyChecker().execute(spec, _trace(start, mismatch), start, mismatch)
    pending = PriceCalculationConsistencyChecker().execute(spec, _trace(start, missing), start, missing)
    assert failed.status == "fail"
    assert "差额 ¥6.00" in failed.reason
    assert pending.status == "needs_verification"


def test_price_checker_supports_english_annual_plan_and_percent_discount():
    registry = _registry()
    spec = registry.get("price-calculation-consistency")
    start = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="Purchase", viewport={"width": 1440, "height": 1000},
    )
    end = start.model_copy(update={"quote_state": {
        "requested_options": ["Personal Advanced", "Annual Plan"],
        "selected_options": ["Personal Advanced ￥198.00 / Month", "Annual Plan 30% off"],
        "summary": {"Specification": "Personal Advanced", "Purchase Duration": "Annual Plan"},
        "total": "1663.20",
    }})

    result = PriceCalculationConsistencyChecker().execute(spec, _trace(start, end), start, end)

    assert result.status == "pass"
    assert "¥198.00 × 12 × 0.7 = ¥1663.20" in result.reason


def test_price_checker_still_calculates_when_an_extra_factor_does_not_change_total():
    registry = _registry()
    spec = registry.get("price-calculation-consistency")
    start = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000},
    )
    end = start.model_copy(update={"quote_state": {
        "requested_options": ["个人高级版", "连续包年"],
        "selected_options": ["个人高级版 ￥198.00/月", "连续包年 7折"],
        "summary": {"购买时长": "连续包年"},
        "total": "1663.20",
        "pricing_complexities": ["优惠券抵扣"],
    }})

    result = PriceCalculationConsistencyChecker().execute(spec, _trace(start, end), start, end)

    assert result.status == "pass"
    assert "¥198.00 × 12 × 0.7 = ¥1663.20" in result.reason
    assert "expected=1663.20" in result.evidence


def test_price_checker_explains_formula_difference_before_requesting_confirmation():
    registry = _registry()
    spec = registry.get("price-calculation-consistency")
    start = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000},
    )
    end = start.model_copy(update={"quote_state": {
        "requested_options": ["个人高级版", "连续包年"],
        "selected_options": ["个人高级版 ￥198.00/月", "连续包年 7折"],
        "summary": {"购买时长": "连续包年"},
        "total": "1600.00",
        "pricing_complexities": ["优惠券抵扣"],
    }})

    result = PriceCalculationConsistencyChecker().execute(spec, _trace(start, end), start, end)

    assert result.status == "needs_verification"
    assert "¥198.00 × 12 × 0.7 = ¥1663.20" in result.reason
    assert "页面显示 ¥1600.00" in result.reason
    assert "差额 ¥63.20" in result.reason
    assert "优惠券抵扣" in result.reason


def test_price_checker_uses_fixed_single_month_duration_and_clicked_card_price():
    registry = _registry()
    spec = registry.get("price-calculation-consistency")
    start = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000},
    )
    end = start.model_copy(update={"quote_state": {
        "requested_options": ["Lite"],
        "requested_option_details": ["Lite 轻量入门 ¥59.00 /月"],
        "selected_options": ["包月", "1个月"],
        "summary": {"计费模式": "包月", "购买时长": "1个月"},
        "total": "59.00",
    }})

    result = PriceCalculationConsistencyChecker().execute(spec, _trace(start, end), start, end)

    assert result.status == "pass"
    assert "¥59.00 × 1 × 1 = ¥59.00" in result.reason
    assert "duration=1个月" in result.evidence


def test_payment_remains_blocked_while_quote_configuration_is_allowed():
    snapshot = PageSnapshot(
        page_id="purchase", requested_url="https://example.test", final_url="https://example.test",
        title="购买", viewport={"width": 1440, "height": 1000}, interactive_elements=[
            InteractiveElement(tag="button", text="立即支付", selector="#pay"),
            InteractiveElement(tag="div", text="个人标准版", selector="#standard",
                               configuration_group="plans", configuration_option="个人标准版"),
            InteractiveElement(tag="div", text="个人高级版", selector="#advanced",
                               configuration_group="plans", configuration_option="个人高级版"),
        ],
    )
    candidates = InteractionDiscovery().discover(snapshot)
    payment = next(item for item in candidates if item.element.text == "立即支付")
    assert payment.execution_decision == "blocked"
    assert payment.risk_level == "mutating"
    assert sum(item.kind == "quote_configuration" for item in candidates) == 2
