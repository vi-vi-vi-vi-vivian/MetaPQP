"""Browser acquisition port."""

from typing import Protocol

from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.domain.models import (
    InteractionCandidate,
    InteractionTrace,
    PageSnapshot,
    PageTarget,
)


class BrowserPort(Protocol):
    async def capture(
        self,
        target: PageTarget,
        run_id: str,
        auth_session: BrowserAuthSession | None = None,
    ) -> PageSnapshot: ...

    async def inspect_interactions(
        self,
        target: PageTarget,
        run_id: str,
        candidates: list[InteractionCandidate],
        auth_session: BrowserAuthSession | None = None,
    ) -> list[InteractionTrace]: ...
