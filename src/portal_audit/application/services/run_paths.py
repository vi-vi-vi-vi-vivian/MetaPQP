"""Stable, human-readable output paths for page audit runs."""

from __future__ import annotations

import re
from pathlib import Path

from portal_audit.domain.models import PageAuditRequest, PageTarget


def _safe_segment(value: str) -> str:
    segment = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return segment or "unknown"


def page_run_relative_dir(
    request: PageAuditRequest,
    target: PageTarget,
    job_id: str,
) -> Path:
    """Return source/product/page/device/locale/job without allowing path traversal."""
    values = (
        request.source,
        request.product or target.page_id,
        target.page_id,
        target.device,
        target.locale,
        job_id,
    )
    return Path(*(_safe_segment(value) for value in values))
