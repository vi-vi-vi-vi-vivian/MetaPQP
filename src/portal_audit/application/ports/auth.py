"""Authentication session port; credentials never cross into domain results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from portal_audit.domain.models import AuthenticationSummary, AuthMode, PageTarget


@dataclass(frozen=True)
class BrowserAuthSession:
    summary: AuthenticationSummary
    storage_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuthAccount:
    account_id: str
    account_type: str
    provider: str
    username: str | None
    password: str | None
    site: str
    enabled: bool = True


class AccountCredentialSourcePort(Protocol):
    def load(self) -> AuthAccount: ...


class AuthSessionProviderPort(Protocol):
    async def prepare(self, target: PageTarget, mode: AuthMode) -> BrowserAuthSession: ...


class AuthenticationRequiredError(RuntimeError):
    """Raised when required authentication cannot be established."""
