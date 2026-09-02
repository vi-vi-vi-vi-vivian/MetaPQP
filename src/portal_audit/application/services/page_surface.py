"""Resolve a page surface before expanding the audit matrix."""

from __future__ import annotations

from urllib.parse import urlsplit

from portal_audit.domain.models import PageSurface


def resolve_page_surface(url: str, explicit: PageSurface | str | None = None) -> PageSurface:
    if explicit:
        return PageSurface(explicit)
    hostname = (urlsplit(url).hostname or "").lower()
    return PageSurface.CONSOLE if hostname.startswith("console.") else PageSurface.PORTAL


def portal_locale_from_url(url: str) -> str:
    """Huawei portal language is encoded in the URL, not browser locale."""
    path = urlsplit(url).path.lower().rstrip("/") + "/"
    return "en-US" if "/intl/en-us/" in path else "zh-CN"
