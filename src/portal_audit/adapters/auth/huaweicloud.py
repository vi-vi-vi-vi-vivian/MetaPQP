"""Huawei Cloud password-login adapter with reusable Playwright storage state."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, Page, TimeoutError, async_playwright

from portal_audit.adapters.browser.launcher import launch_chromium
from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.domain.models import (
    AuthenticationSummary,
    AuthMode,
    AuthStatus,
    PageTarget,
)

LOGIN_URLS = {
    "cn": "https://auth.huaweicloud.com/authui/login.html#/login",
    "intl": "https://auth.huaweicloud.com/authui/login.html?locale=en-us#/login",
}
VALIDATION_URLS = {
    "cn": "https://console.huaweicloud.com/console/?region=cn-east-3#/home",
    "intl": "https://console-intl.huaweicloud.com/?locale=en-us",
}


class HuaweiCloudAuthProvider:
    id = "huaweicloud-password"

    def __init__(
        self,
        *,
        username: str | None,
        password: str | None,
        state_path: Path,
        account_id: str = "default",
        account_type: str = "huawei_cloud_account",
        enabled: bool = True,
        site: str = "cn",
        timeout_ms: int = 60_000,
        headless: bool = True,
        force_login: bool = False,
        interactive: bool = False,
    ):
        if site not in LOGIN_URLS:
            raise ValueError(f"Unsupported Huawei Cloud site: {site}")
        self.username = username
        self.password = password
        self.account_id = account_id
        self.account_type = account_type
        self.enabled = enabled
        self.state_path = state_path
        self.site = site
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.force_login = force_login
        self.interactive = interactive

    @staticmethod
    def supports(target: PageTarget) -> bool:
        host = (urlparse(target.url).hostname or "").lower()
        return host == "huaweicloud.com" or host.endswith(".huaweicloud.com")

    async def prepare(self, target: PageTarget, mode: AuthMode) -> BrowserAuthSession:
        if mode == AuthMode.OFF or not self.supports(target):
            return BrowserAuthSession(AuthenticationSummary())
        if not self.enabled:
            return self._anonymous(AuthStatus.FAILED, "account_disabled")

        async with async_playwright() as playwright:
            browser = await launch_chromium(
                playwright.chromium,
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                cached = self._load_state()
                if not self.force_login and cached and await self._validate(browser, cached):
                    return self._authenticated(cached, "cache")
                if not self.username or not self.password:
                    return self._anonymous(
                        AuthStatus.FAILED,
                        "credentials_missing_in_account_config",
                    )
                return await self._login(browser)
            finally:
                await browser.close()

    def _load_state(self) -> dict | None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        cookies = state.get("cookies", []) if isinstance(state, dict) else []
        return (
            state if any("huaweicloud.com" in item.get("domain", "") for item in cookies) else None
        )

    async def _validate(self, browser: Browser, state: dict) -> bool:
        context = await browser.new_context(storage_state=state)
        page = await context.new_page()
        try:
            await page.goto(
                VALIDATION_URLS[self.site],
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            await page.wait_for_timeout(2_000)
            return not self._is_login_url(page.url) and not await self._has_login_prompt(page)
        except TimeoutError:
            return False
        finally:
            await context.close()

    async def _login(self, browser: Browser) -> BrowserAuthSession:
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        page.set_default_timeout(min(self.timeout_ms, 10_000))
        try:
            await page.goto(
                LOGIN_URLS[self.site],
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            return await self.continue_password_login(page)
        except TimeoutError:
            return self._anonymous(AuthStatus.FAILED, "login_timeout")
        finally:
            await context.close()

    async def continue_password_login(self, page: Page, *, persist: bool = True) -> BrowserAuthSession:
        """Submit credentials on the existing login page, preserving its service redirect."""
        if not self._is_login_url(page.url):
            return self._anonymous(AuthStatus.FAILED, "unsupported_login_origin")
        if not self.enabled or not self.username or not self.password:
            return self._anonymous(AuthStatus.FAILED, "credentials_missing_in_account_config")
        local_security_service_failed = False

        def remember_local_security_service_failure(request) -> None:
            nonlocal local_security_service_failed
            # Huawei's account-risk component asks this loopback service for
            # device-verification information.  A refused connection is not a
            # page resource failure and must never be bypassed by automation.
            if request.url.startswith(("https://127.0.0.1:46681/", "http://127.0.0.1:46681/")):
                local_security_service_failed = True

        page.on("requestfailed", remember_local_security_service_failure)
        try:
            if await self.requires_challenge(page):
                return self._anonymous(AuthStatus.CHALLENGE_REQUIRED, "captcha_or_mfa_required")
            await self._open_password_form(page)
            if await self.requires_challenge(page):
                return self._anonymous(AuthStatus.CHALLENGE_REQUIRED, "captcha_or_mfa_required")
            if not self._is_login_url(page.url):
                return self._anonymous(AuthStatus.FAILED, "unsupported_login_origin")
            if not await self._fill_credentials(page):
                return self._anonymous(AuthStatus.FAILED, "login_form_not_supported")
            await self._submit(page)
            status, reason = await self._wait_for_result(page, stop_on_challenge=True)
            if status == AuthStatus.FAILED and reason == "login_result_timeout" and local_security_service_failed:
                return self._anonymous(
                    AuthStatus.FAILED, "local_security_service_unavailable"
                )
            if status != AuthStatus.AUTHENTICATED:
                return self._anonymous(status, reason)
            state = await page.context.storage_state()
            if persist:
                self._save_state(state)
            return self._authenticated(state, "password")
        except TimeoutError:
            return self._anonymous(AuthStatus.FAILED, "login_timeout")

    @staticmethod
    async def requires_challenge(page: Page) -> bool:
        text = (await page.locator('body').inner_text(timeout=5_000)).lower()
        title = (await page.title()).lower()
        # A "验证码登录" alternative tab is not itself an active challenge.
        if any(marker in title for marker in ('security verification', '安全验证', '身份验证')):
            return True
        if any(marker in text for marker in (
            '请完成安全验证', '请拖动滑块', '拖动滑块完成', '请输入短信验证码',
            '请输入手机验证码', '请输入动态验证码', '验证码已发送',
            'verify you are human', 'verify your identity', 'complete the captcha',
            'enter the verification code', 'enter the code sent',
        )):
            return True
        controls = page.locator(
            'input[autocomplete="one-time-code"]:visible, '
            'input[name*="captcha" i]:visible, input[name*="smscode" i]:visible, '
            'input[placeholder*="验证码"]:visible, '
            'iframe[src*="captcha" i]:visible, [class*="captcha-slider" i]:visible'
        )
        return await controls.count() > 0

    async def _open_password_form(self, page: Page) -> None:
        # The tab is visible before Huawei's SPA attaches its click handler.
        # Waiting for the default form prevents an early click from being lost.
        try:
            await page.locator('input:not([type="hidden"]):visible').first.wait_for(
                state="visible",
                timeout=min(self.timeout_ms, 30_000),
            )
        except TimeoutError:
            pass
        if await self._first_visible(page.locator('input[type="password"]')) is not None:
            return
        password_tab = page.locator("#pwdLogin")
        visible_tab = await self._first_visible(password_tab)
        if visible_tab is not None:
            await visible_tab.click()
            await self._wait_for_password_form(page)
            return
        for label in ("Password Login", "密码登录"):
            target = page.get_by_text(label, exact=True)
            visible_target = await self._first_visible(target)
            if visible_target is not None:
                await visible_target.click()
                await self._wait_for_password_form(page)
                return
        await self._wait_for_password_form(page)

    async def _wait_for_password_form(self, page: Page) -> None:
        try:
            await page.locator('input[type="password"]').first.wait_for(
                state="visible",
                timeout=min(self.timeout_ms, 30_000),
            )
        except TimeoutError:
            # _fill_credentials returns a stable unsupported-form result.
            pass

    async def _fill_credentials(self, page: Page) -> bool:
        username = page.locator(
            'input[name="userAccount"], input[name="account"], input[name="username"], '
            'input[type="text"], input[type="email"]'
        )
        password = page.locator('input[name="password"], input[type="password"]')
        visible_username = await self._first_visible(username)
        visible_password = await self._first_visible(password)
        if visible_username is None or visible_password is None:
            return False
        await visible_username.fill(self.username or "")
        await visible_password.fill(self.password or "")
        # Huawei's current Vue form enables its submit handler during the
        # password field's blur validation.  A real mouse click blurs first;
        # make that state transition explicit for the isolated browser too.
        await visible_password.press("Tab")
        await page.wait_for_timeout(150)
        return True

    @staticmethod
    async def _first_visible(locator):
        for index in range(await locator.count()):
            candidate = locator.nth(index)
            if await candidate.is_visible():
                return candidate
        return None

    async def _submit(self, page: Page) -> None:
        # The current Huawei account form is a Vue widget whose active
        # password-submit control is a ``div`` rather than a native button.
        # Its visible text is duplicated by a hidden IAM form, so selecting by
        # text first can click an inert element and leave the login waiting
        # until timeout.  Prefer the widget's stable telemetry hook.
        for selector in (
            '[ht="click_pwdlogin_submitLogin"]',
            '.hwid-pwdlogin-root .normalBtn:not(.hwid-disabled)',
            'button[type="submit"]',
            'input[type="submit"]',
            "#btn_submit",
        ):
            target = page.locator(selector)
            visible_target = await self._first_visible(target)
            if visible_target is not None:
                await visible_target.click()
                return
        for label in ("LOG IN", "Log In", "登录"):
            target = page.get_by_text(label, exact=True)
            visible_target = await self._first_visible(target)
            if visible_target is not None:
                await visible_target.click()
                return
        await page.keyboard.press("Enter")

    async def _wait_for_result(self, page: Page, *, stop_on_challenge: bool = False) -> tuple[AuthStatus, str]:
        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline:
            if (stop_on_challenge or not self.interactive) and await self.requires_challenge(page):
                return AuthStatus.CHALLENGE_REQUIRED, "captcha_or_mfa_required"
            if not self._is_login_url(page.url) and self._has_huawei_cookie(
                await page.context.cookies()
            ):
                return AuthStatus.AUTHENTICATED, "password_login_succeeded"
            text = (await page.locator("body").inner_text(timeout=5_000)).lower()
            if any(
                marker in text
                for marker in (
                    "incorrect password",
                    "invalid account",
                    "用户名或密码错误",
                    "账号或密码错误",
                )
            ):
                return AuthStatus.FAILED, "credentials_rejected"
            await page.wait_for_timeout(1_000)
        return AuthStatus.FAILED, "login_result_timeout"

    async def _has_login_prompt(self, page: Page) -> bool:
        try:
            text = (await page.locator("body").inner_text(timeout=5_000)).lower()
        except TimeoutError:
            return True
        return "password login" in text or "密码登录" in text

    @staticmethod
    def _is_login_url(url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'auth.huaweicloud.com'
                and 'login' in parsed.path.lower())

    @staticmethod
    def _has_huawei_cookie(cookies: list[dict]) -> bool:
        return any("huaweicloud.com" in item.get("domain", "") for item in cookies)

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        self.state_path.chmod(0o600)

    def _authenticated(self, state: dict, source: str) -> BrowserAuthSession:
        return BrowserAuthSession(
            AuthenticationSummary(
                provider=self.id,
                status=AuthStatus.AUTHENTICATED,
                account_id=self.account_id,
                account_type=self.account_type,
                source=source,
                reason="authenticated session available",
            ),
            storage_state=state,
        )

    def _anonymous(self, status: AuthStatus, reason: str) -> BrowserAuthSession:
        return BrowserAuthSession(
            AuthenticationSummary(
                provider=self.id,
                status=status,
                account_id=self.account_id,
                account_type=self.account_type,
                reason=reason,
            )
        )
