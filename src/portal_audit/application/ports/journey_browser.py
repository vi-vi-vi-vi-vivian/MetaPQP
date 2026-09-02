"""Stateful browser port for a supervised sequence of registered transitions."""

from dataclasses import dataclass, field
from typing import Protocol

from portal_audit.application.ports.auth import BrowserAuthSession
from portal_audit.domain.models import (
    PageMapNode,
    PageSnapshot,
    PageTarget,
    SafetyProfile,
    TransitionDefinition,
    TransitionTrace,
)


@dataclass(frozen=True)
class JourneyBrowserRun:
    start_snapshot: PageSnapshot
    end_snapshot: PageSnapshot
    trace: TransitionTrace
    snapshots: list[PageSnapshot] = field(default_factory=list)
    traces: list[TransitionTrace] = field(default_factory=list)

    def __post_init__(self):
        if not self.snapshots:
            object.__setattr__(self, "snapshots", [self.start_snapshot, self.end_snapshot])
        if not self.traces:
            object.__setattr__(self, "traces", [self.trace])


@dataclass(frozen=True)
class JourneyBrowserStep:
    transition: TransitionDefinition
    start_node: PageMapNode
    end_node: PageMapNode
    start_target: PageTarget
    end_target: PageTarget
    start_run_id: str
    end_run_id: str


class BrowserJourneySessionPort(Protocol):
    async def run_journey(
        self,
        *,
        steps: list[JourneyBrowserStep],
        safety_profile: SafetyProfile,
        auth_session: BrowserAuthSession,
    ) -> JourneyBrowserRun: ...

    async def run_transition(
        self,
        *,
        transition: TransitionDefinition,
        start_node: PageMapNode,
        end_node: PageMapNode,
        start_target: PageTarget,
        end_target: PageTarget,
        start_run_id: str,
        end_run_id: str,
        safety_profile: SafetyProfile,
        auth_session: BrowserAuthSession,
    ) -> JourneyBrowserRun: ...
