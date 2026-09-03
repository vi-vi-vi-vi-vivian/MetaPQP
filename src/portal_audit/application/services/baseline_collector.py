from portal_audit.application.ports.auth import (
    AuthenticationRequiredError,
    AuthSessionProviderPort,
)
from portal_audit.application.ports.browser import BrowserPort
from portal_audit.domain.models import (
    AuthenticationSummary,
    AuthMode,
    AuthStatus,
    PageSnapshot,
    PageTarget,
)


class BaselineCollector:
    def __init__(
        self,
        browser: BrowserPort,
        auth_provider: AuthSessionProviderPort | None,
    ):
        self.browser = browser
        self.auth_provider = auth_provider

    async def collect(
        self, target: PageTarget, run_id: str, auth_mode: AuthMode = AuthMode.AUTO
    ) -> PageSnapshot:
        if auth_mode == AuthMode.OFF:
            snapshot = await self.browser.capture(target, run_id, None)
            snapshot.authentication = AuthenticationSummary()
            return snapshot
        if self.auth_provider is None:
            raise AuthenticationRequiredError("no authentication provider is configured")
        auth_session = await self.auth_provider.prepare(target, auth_mode)
        if (
            auth_mode == AuthMode.REQUIRED
            and auth_session.summary.status != AuthStatus.AUTHENTICATED
        ):
            raise AuthenticationRequiredError(
                auth_session.summary.reason or "required authentication could not be established"
            )
        snapshot = await self.browser.capture(target, run_id, auth_session)
        snapshot.authentication = auth_session.summary
        return snapshot
