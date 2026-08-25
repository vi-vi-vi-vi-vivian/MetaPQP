import json
import stat
from unittest.mock import AsyncMock, MagicMock

import pytest

from portal_audit.adapters.auth.config import YamlAccountCredentialSource
from portal_audit.adapters.auth.huaweicloud import HuaweiCloudAuthProvider
from portal_audit.application.ports.auth import (
    AuthenticationRequiredError,
    BrowserAuthSession,
)
from portal_audit.application.services.baseline_collector import BaselineCollector
from portal_audit.domain.models import (
    AuthenticationSummary,
    AuthMode,
    AuthStatus,
    PageSnapshot,
    PageTarget,
)


def target(url="https://www.huaweicloud.com/product/demo.html"):
    return PageTarget(
        page_id="demo",
        url=url,
        source="web",
        product="demo",
        device="desktop",
        locale="zh-CN",
    )


def test_single_account_config_loads_extension_metadata(tmp_path):
    config_path = tmp_path / "account.local.yaml"
    config_path.write_text(
        """\
version: "1"
account:
  id: primary
  account_type: buyer
  provider: huaweicloud
  enabled: true
  site: cn
  username: test-user
  password: test-password
""",
        encoding="utf-8",
    )

    account = YamlAccountCredentialSource(config_path).load()

    assert account.account_id == "primary"
    assert account.account_type == "buyer"
    assert account.provider == "huaweicloud"
    assert account.username == "test-user"
    assert account.password == "test-password"
    assert account.site == "cn"
    assert account.enabled is True


class FakeAuthProvider:
    def __init__(self, status):
        self.session = BrowserAuthSession(
            AuthenticationSummary(provider="fake", status=status, reason="test")
        )

    async def prepare(self, page_target, mode):
        return self.session


class FakeBrowser:
    def __init__(self):
        self.received_session = None

    async def capture(self, page_target, run_id, auth_session=None):
        self.received_session = auth_session
        return PageSnapshot(
            page_id=page_target.page_id,
            requested_url=page_target.url,
            final_url=page_target.url,
            title="Demo",
            viewport={"width": 1440, "height": 1000},
        )


def test_huawei_provider_scope_and_private_state_file(tmp_path):
    provider = HuaweiCloudAuthProvider(
        username=None,
        password=None,
        state_path=tmp_path / "auth.json",
    )
    state = {
        "cookies": [{"name": "session", "value": "secret", "domain": ".huaweicloud.com"}],
        "origins": [],
    }

    provider._save_state(state)

    assert provider.supports(target())
    assert not provider.supports(target("https://example.com"))
    assert provider._load_state() == state
    assert stat.S_IMODE(provider.state_path.stat().st_mode) == 0o600
    assert json.loads(provider.state_path.read_text()) == state


def test_huawei_provider_exposes_account_metadata_without_credentials(tmp_path):
    provider = HuaweiCloudAuthProvider(
        username="test-user",
        password="test-password",
        state_path=tmp_path / "auth.json",
        account_id="primary",
        account_type="buyer",
    )

    summary = provider._anonymous(AuthStatus.FAILED, "test").summary

    assert summary.account_id == "primary"
    assert summary.account_type == "buyer"
    assert "test-user" not in summary.model_dump_json()
    assert "test-password" not in summary.model_dump_json()


async def test_password_login_waits_for_async_form_render(tmp_path):
    provider = HuaweiCloudAuthProvider(
        username="test-user",
        password="test-password",
        state_path=tmp_path / "auth.json",
    )
    page = MagicMock()
    password_tab = MagicMock()
    password_tab.count = AsyncMock(return_value=1)
    visible_tab = MagicMock()
    visible_tab.is_visible = AsyncMock(return_value=True)
    visible_tab.click = AsyncMock()
    password_tab.nth.return_value = visible_tab
    ready_input = MagicMock()
    ready_input.first.wait_for = AsyncMock()
    password_input = MagicMock()
    password_input.count = AsyncMock(return_value=0)
    password_input.first.wait_for = AsyncMock()
    page.locator.side_effect = lambda selector: {
        'input:not([type="hidden"]):visible': ready_input,
        'input[type="password"]': password_input,
        "#pwdLogin": password_tab,
    }[selector]

    await provider._open_password_form(page)

    ready_input.first.wait_for.assert_awaited_once_with(
        state="visible",
        timeout=30_000,
    )
    visible_tab.click.assert_awaited_once()
    password_input.first.wait_for.assert_awaited_once_with(
        state="visible",
        timeout=30_000,
    )


async def test_password_login_fills_visible_inputs_in_multi_mode_form(tmp_path):
    provider = HuaweiCloudAuthProvider(
        username="test-user",
        password="test-password",
        state_path=tmp_path / "auth.json",
    )
    hidden_username = MagicMock()
    hidden_username.is_visible = AsyncMock(return_value=False)
    visible_username = MagicMock()
    visible_username.is_visible = AsyncMock(return_value=True)
    visible_username.fill = AsyncMock()
    hidden_password = MagicMock()
    hidden_password.is_visible = AsyncMock(return_value=False)
    visible_password = MagicMock()
    visible_password.is_visible = AsyncMock(return_value=True)
    visible_password.fill = AsyncMock()
    username_locator = MagicMock()
    username_locator.count = AsyncMock(return_value=2)
    username_locator.nth.side_effect = [hidden_username, visible_username]
    password_locator = MagicMock()
    password_locator.count = AsyncMock(return_value=2)
    password_locator.nth.side_effect = [hidden_password, visible_password]
    page = MagicMock()
    page.locator.side_effect = [username_locator, password_locator]

    filled = await provider._fill_credentials(page)

    assert filled is True
    visible_username.fill.assert_awaited_once_with("test-user")
    visible_password.fill.assert_awaited_once_with("test-password")


async def test_baseline_passes_authenticated_session_without_exposing_storage_state():
    browser = FakeBrowser()
    collector = BaselineCollector(browser, FakeAuthProvider(AuthStatus.AUTHENTICATED))

    snapshot = await collector.collect(target(), "run", AuthMode.REQUIRED)

    assert browser.received_session.summary.status == AuthStatus.AUTHENTICATED
    assert snapshot.authentication.status == AuthStatus.AUTHENTICATED
    assert "storage_state" not in snapshot.model_dump(mode="json")


async def test_required_authentication_stops_before_page_capture():
    browser = FakeBrowser()
    collector = BaselineCollector(browser, FakeAuthProvider(AuthStatus.CHALLENGE_REQUIRED))

    with pytest.raises(AuthenticationRequiredError, match="test"):
        await collector.collect(target(), "run", AuthMode.REQUIRED)

    assert browser.received_session is None
