"""Load a SKILL.md package without coupling planning to its prose."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    version: str
    instructions: str
    path: Path


class SkillLoader:
    def __init__(self, root: Path):
        self.root = root

    def load(self, skill_id: str) -> LoadedSkill:
        path = self.root / skill_id / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"Skill {skill_id} is missing YAML frontmatter")
        _, frontmatter, body = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        package_metadata = metadata.get("metadata", {})
        return LoadedSkill(
            name=metadata["name"],
            description=metadata["description"],
            version=str(metadata.get("version", package_metadata.get("version", "1.0.0"))),
            instructions=body.strip(),
            path=path,
        )
