"""Local filesystem artifact store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from portal_audit.domain.models import ArtifactRef


class LocalArtifactStore:
    def __init__(self, root: Path):
        self.root = root

    def run_dir(self, run_id: str) -> Path:
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, run_id: str, name: str, value: str, media_type: str) -> ArtifactRef:
        path = self.run_dir(run_id) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return ArtifactRef(kind=name, path=str(path), media_type=media_type)

    def write_json(self, run_id: str, name: str, value: Any) -> ArtifactRef:
        return self.write_text(
            run_id,
            name,
            json.dumps(value, ensure_ascii=False, indent=2, default=str),
            "application/json",
        )
