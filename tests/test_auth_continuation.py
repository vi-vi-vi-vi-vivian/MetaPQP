from unittest.mock import AsyncMock, Mock

import pytest

from portal_audit.adapters.auth.huaweicloud import HuaweiCloudAuthProvider
from portal_audit.domain.models import AuthStatus


def provider(tmp_path):
    return HuaweiCloudAuthProvider(username='test-user', password='test-password', state_path=tmp_path / 'state.json')


@pytest.mark.parametrize('url', ['https://auth.huaweicloud.com.evil.test/authui/login.html',
                               'https://evil.test/?next=auth.huaweicloud.com/login',
                               'http://auth.huaweicloud.com/authui/login.html'])
async def test_credentials_never_sent_to_untrusted_login_origin(tmp_path, url):
    auth = provider(tmp_path)
    auth._fill_credentials = AsyncMock()
    result = await auth.continue_password_login(Mock(url=url))
    assert result.summary.status == AuthStatus.FAILED
    auth._fill_credentials.assert_not_awaited()


@pytest.mark.parametrize('challenge', [False, True])
async def test_password_continuation_preserves_target_and_stops_on_challenge(tmp_path, challenge):
    auth = provider(tmp_path)
    page = Mock(url='https://auth.huaweicloud.com/authui/login.html?service=original-target')
    page.context.storage_state = AsyncMock(return_value={'cookies': [], 'origins': []})
    page.goto = AsyncMock()
    auth.requires_challenge = AsyncMock(return_value=False)
    auth._open_password_form = AsyncMock()
    auth._fill_credentials = AsyncMock(return_value=True)
    auth._submit = AsyncMock()
    auth._wait_for_result = AsyncMock(return_value=(AuthStatus.CHALLENGE_REQUIRED if challenge else AuthStatus.AUTHENTICATED, 'test'))
    result = await auth.continue_password_login(page)
    page.goto.assert_not_awaited()
    auth._submit.assert_awaited_once()
    auth._wait_for_result.assert_awaited_once_with(page, stop_on_challenge=True)
    assert result.summary.status == (AuthStatus.CHALLENGE_REQUIRED if challenge else AuthStatus.AUTHENTICATED)
    assert auth.state_path.exists() is not challenge


async def test_sms_login_tab_is_not_an_active_challenge(tmp_path):
    page = Mock()
    page.title = AsyncMock(return_value='用户登录')
    locator = Mock(inner_text=AsyncMock(return_value='密码登录 验证码登录'), count=AsyncMock(return_value=0))
    page.locator.return_value = locator
    assert not await provider(tmp_path).requires_challenge(page)
    locator.inner_text.return_value = '请输入短信验证码'
    assert await provider(tmp_path).requires_challenge(page)


async def test_temporary_login_does_not_persist_session(tmp_path):
    auth = provider(tmp_path)
    page = Mock(url='https://auth.huaweicloud.com/authui/login.html?service=target')
    page.context.storage_state = AsyncMock(return_value={'cookies': [], 'origins': []})
    auth.requires_challenge = AsyncMock(return_value=False)
    auth._open_password_form = AsyncMock()
    auth._fill_credentials = AsyncMock(return_value=True)
    auth._submit = AsyncMock()
    auth._wait_for_result = AsyncMock(return_value=(AuthStatus.AUTHENTICATED, 'test'))
    result = await auth.continue_password_login(page, persist=False)
    assert result.summary.status == AuthStatus.AUTHENTICATED
    assert not auth.state_path.exists()


async def test_login_stops_when_huawei_local_security_service_is_unavailable(tmp_path):
    auth = provider(tmp_path)
    page = Mock(url='https://auth.huaweicloud.com/authui/login.html?service=target')
    callbacks = {}
    page.on.side_effect = lambda event, callback: callbacks.setdefault(event, callback)
    auth.requires_challenge = AsyncMock(return_value=False)
    auth._open_password_form = AsyncMock()
    auth._fill_credentials = AsyncMock(return_value=True)
    auth._submit = AsyncMock(side_effect=lambda _: callbacks['requestfailed'](
        Mock(url='https://127.0.0.1:46681/')
    ))
    auth._wait_for_result = AsyncMock(return_value=(AuthStatus.FAILED, 'login_result_timeout'))

    result = await auth.continue_password_login(page)

    assert result.summary.status == AuthStatus.FAILED
    assert result.summary.reason == 'local_security_service_unavailable'


async def test_challenge_checked_before_existing_cookie_can_imply_success(tmp_path):
    auth = provider(tmp_path)
    auth.requires_challenge = AsyncMock(return_value=True)
    page = Mock(url='https://console.huaweicloud.com/verification')
    page.context.cookies = AsyncMock(return_value=[{'domain': '.huaweicloud.com'}])
    status, _ = await auth._wait_for_result(page, stop_on_challenge=True)
    assert status == AuthStatus.CHALLENGE_REQUIRED
    page.context.cookies.assert_not_awaited()
