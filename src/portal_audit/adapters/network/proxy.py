"""Resolve an outbound model proxy without coupling domain code to macOS."""

from __future__ import annotations

import urllib.request


def resolve_https_proxy(explicit_proxy: str | None = None) -> str | None:
    """Prefer explicit configuration, then environment/macOS system proxy settings."""
    if explicit_proxy and explicit_proxy.strip():
        return explicit_proxy.strip()
    proxies = urllib.request.getproxies()
    candidate = proxies.get("https") or proxies.get("http")
    return str(candidate).strip() if candidate else None
