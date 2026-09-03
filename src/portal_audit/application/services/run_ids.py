"""Identifiers shared by local audit runners without framework dependencies."""

from __future__ import annotations

from datetime import datetime


def new_job_id() -> str:
    """Return a locally readable, chronologically sortable run identifier."""

    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
