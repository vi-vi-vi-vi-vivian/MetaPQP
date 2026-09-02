"""Deterministic URL-to-PageMapNode resolution."""

from __future__ import annotations

from fnmatch import fnmatchcase
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from portal_audit.domain.models import PageMapNodeResolution
from portal_audit.domain.registry import PageMapRegistry

VOLATILE_QUERY_KEYS = {"locale", "region", "agencyid", "agency_id"}


class PageMapNodeResolver:
    def __init__(self, registry: PageMapRegistry):
        self.registry = registry

    def resolve(self, url: str) -> PageMapNodeResolution:
        normalized = normalize_page_map_url(url)
        matches = [
            (node, pattern)
            for node in self.registry.all()
            for pattern in node.url_patterns
            if fnmatchcase(normalized, normalize_page_map_pattern(pattern))
        ]
        if not matches:
            return PageMapNodeResolution(
                status="unmapped",
                reason=f"No PageMapNode pattern matched {normalized}",
            )
        ranked = sorted(
            matches,
            key=lambda item: _pattern_specificity(item[1]),
            reverse=True,
        )
        best_score = _pattern_specificity(ranked[0][1])
        best = [item for item in ranked if _pattern_specificity(item[1]) == best_score]
        node_ids = {item[0].id for item in best}
        if len(node_ids) > 1:
            return PageMapNodeResolution(
                status="ambiguous",
                reason=f"Equally specific PageMapNode patterns matched: {sorted(node_ids)}",
            )
        node, pattern = best[0]
        return PageMapNodeResolution(
            node_id=node.id,
            node_version=node.version,
            matched_pattern=pattern,
            status="matched",
            reason="Most specific deterministic URL pattern matched",
        )


def normalize_page_map_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in VOLATILE_QUERY_KEYS
    ]
    path = parsed.path or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(sorted(query)),
            parsed.fragment,
        )
    )


def normalize_page_map_pattern(pattern: str) -> str:
    parsed = urlsplit(pattern)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in VOLATILE_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            urlencode(sorted(query)),
            parsed.fragment,
        )
    )


def _pattern_specificity(pattern: str) -> tuple[int, int]:
    wildcard_count = pattern.count("*") + pattern.count("?")
    return (len(pattern) - wildcard_count, -wildcard_count)
