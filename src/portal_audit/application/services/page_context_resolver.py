"""Merge pluggable detector observations with explicit request overrides."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from portal_audit.domain.models import PageAuditRequest, PageContext, PageSnapshot


class PageContextResolver:
    def __init__(self, detectors: Iterable[Any]):
        self.detectors = tuple(detectors)

    def resolve(self, request: PageAuditRequest, snapshot: PageSnapshot) -> PageContext:
        observations = [obs for detector in self.detectors for obs in detector.detect(snapshot)]
        stages = sorted(
            (obs for obs in observations if obs.dimension == "journey_stage"),
            key=lambda item: item.confidence,
            reverse=True,
        )
        archetypes = sorted(
            (obs for obs in observations if obs.dimension == "page_archetype"),
            key=lambda item: item.confidence,
            reverse=True,
        )
        primary_stage = request.journey_stage or (stages[0].value if stages else "unknown")
        primary_archetype = request.page_archetype or (
            archetypes[0].value if archetypes else "content_page"
        )
        features = sorted(
            {obs.value for obs in observations if obs.dimension == "feature"}
            | set(request.feature_overrides)
        )
        return PageContext(
            primary_journey_stage=primary_stage,
            related_journey_stages=[obs.value for obs in stages[1:] if obs.value != primary_stage],
            page_archetypes=[primary_archetype],
            features=features,
            observations=observations,
        )
