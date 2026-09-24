from unittest.mock import AsyncMock, Mock

import pytest

from portal_audit.adapters.browser.playwright_browser import PlaywrightBrowser
from portal_audit.application.services.interaction_feedback import (
    local_state_feedback,
    subscription_selection_feedback,
)
from portal_audit.domain.models import InteractionCandidate, InteractiveElement


def test_collapsing_default_open_panel_is_valid_feedback():
    result = local_state_feedback({'expanded': 'true', 'panel_visible': True},
                                  {'expanded': 'false', 'panel_visible': False})
    assert result and '收起' in result


def test_already_open_panel_is_not_a_missing_content_failure():
    state = {'expanded': 'true', 'panel_visible': True, 'panel_text': '支持的模型说明'}
    assert local_state_feedback(state, state)
    assert local_state_feedback({}, {}) is None


def test_already_selected_purchase_card_is_valid_feedback():
    state = {'selection_control': True, 'selected': True}
    assert local_state_feedback(state, state)


def test_expanded_attribute_alone_does_not_prove_panel_visible():
    assert local_state_feedback({'expanded': 'false'}, {'expanded': 'true', 'panel_visible': False}) is None


def test_subscription_management_fails_when_plan_choice_is_not_carried_to_next_step():
    url = 'https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/resourcePlanManagement'
    candidate = InteractionCandidate(
        element=InteractiveElement(tag='a', text='立即订阅', href=url), kind='navigation',
        risk_level='read_only', execution_decision='allowed', surrounding_text='Lite ¥59.00 立即订阅',
    )
    status, reason, suggestion = subscription_selection_feedback(
        candidate, url, '资源套餐管理 全部套餐 Lite Standard Pro Max 补货时间'
    )
    assert status == 'fail'
    assert '未显示 Lite 已选中' in reason
    assert '携带 Lite 套餐标识' in suggestion


def test_subscription_management_requires_the_actual_management_destination():
    candidate = InteractionCandidate(
        element=InteractiveElement(tag='a', text='立即订阅', href='https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/resourcePlanManagement'),
        kind='navigation', risk_level='read_only', execution_decision='allowed',
    )
    assert subscription_selection_feedback(candidate, 'https://console.huaweicloud.com/modelarts/#/home', '') is None


def test_subscription_management_passes_when_selected_plan_and_order_step_are_visible():
    url = 'https://console.huaweicloud.com/modelarts/?region=cn-southwest-2#/model-studio/resourcePlanManagement'
    candidate = InteractionCandidate(
        element=InteractiveElement(tag='a', text='立即订阅', href=url), kind='navigation',
        risk_level='read_only', execution_decision='allowed', surrounding_text='Lite ¥59.00 立即订阅',
    )
    status, _, _ = subscription_selection_feedback(candidate, url, '当前套餐 Lite 已选择 确认订单')
    assert status == 'pass'


@pytest.mark.parametrize('key', ['selected', 'checked', 'open'])
def test_deselecting_or_closing_is_valid(key):
    assert local_state_feedback({key: True}, {key: False})


async def test_waits_past_loading_shell_until_content_stabilizes(tmp_path):
    from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
    adapter = PlaywrightBrowser(LocalArtifactStore(tmp_path), timeout_ms=5000)
    shell = {'text': '控制台 Loading...', 'busy': True, 'content': 200}
    content = {'text': '套餐购买正文', 'busy': False, 'content': 200}
    adapter._result_probe = AsyncMock(side_effect=[shell, shell, content, content, content, content])
    page = Mock(wait_for_timeout=AsyncMock())
    result = await adapter._wait_for_interaction_content(page)
    assert result == {'text': '套餐购买正文', 'ready': True}
    assert adapter._result_probe.await_count == 6


async def test_loading_timeout_does_not_claim_ready(tmp_path):
    from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
    adapter = PlaywrightBrowser(LocalArtifactStore(tmp_path), timeout_ms=1500)
    adapter._result_probe = AsyncMock(return_value={'text': 'Loading...', 'busy': True, 'content': 200})
    result = await adapter._wait_for_interaction_content(Mock(wait_for_timeout=AsyncMock()))
    assert result['ready'] is False


async def test_edgeone_reason_distinguishes_connection_check_from_login(tmp_path):
    from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
    adapter = PlaywrightBrowser(LocalArtifactStore(tmp_path))
    adapter._primary_body = lambda _: Mock(inner_text=AsyncMock(return_value='正在验证连接安全性 Protected by Tencent Cloud EdgeOne'))
    reason = await adapter._challenge_reason(Mock())
    assert 'EdgeOne' in reason
    assert '不是账号登录要求' in reason
