"""Artifact persistence port."""

from pathlib import Path
from typing import Any, Protocol

from portal_audit.domain.models import ArtifactRef


class ArtifactStorePort(Protocol):
    def run_dir(self, run_id: str) -> Path: ...
    def write_text(self, run_id: str, name: str, value: str, media_type: str) -> ArtifactRef: ...
    def write_json(self, run_id: str, name: str, value: Any) -> ArtifactRef: ...
