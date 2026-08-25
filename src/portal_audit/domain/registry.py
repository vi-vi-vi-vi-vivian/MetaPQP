"""Versioned CheckSpec registry."""

from __future__ import annotations

from pathlib import Path

import yaml

from portal_audit.domain.models import (
    CheckSpec,
    StandardCriterion,
    StandardReference,
    StandardSource,
    StandardSourceStatus,
)


class StandardsRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.sources: dict[str, StandardSource] = {}
        self.criteria: dict[str, StandardCriterion] = {}

    def load(self) -> StandardsRegistry:
        source_payload = yaml.safe_load(
            (self.root / "sources.yaml").read_text(encoding="utf-8")
        ) or {"sources": []}
        criterion_payload = yaml.safe_load(
            (self.root / "criteria.yaml").read_text(encoding="utf-8")
        ) or {"criteria": []}
        sources = [StandardSource.model_validate(raw) for raw in source_payload["sources"]]
        criteria = [StandardCriterion.model_validate(raw) for raw in criterion_payload["criteria"]]
        self._reject_duplicate_ids(sources, "standard source")
        self._reject_duplicate_ids(criteria, "standard criterion")
        self.sources = {item.id: item for item in sources}
        self.criteria = {item.id: item for item in criteria}
        for criterion in self.criteria.values():
            if criterion.source_id not in self.sources:
                raise ValueError(
                    f"Standard criterion {criterion.id} references unknown source "
                    f"{criterion.source_id}"
                )
        return self

    @staticmethod
    def _reject_duplicate_ids(items: list, label: str) -> None:
        ids = [item.id for item in items]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate {label} IDs: {', '.join(duplicates)}")

    def validate_reference(self, reference: StandardReference) -> None:
        criterion = self.criteria.get(reference.criterion_id)
        if criterion is None:
            raise ValueError(f"Unknown standard criterion: {reference.criterion_id}")
        source = self.sources[criterion.source_id]
        if source.status == StandardSourceStatus.RESERVED:
            raise ValueError(
                f"Reserved standard source {source.id} cannot be referenced by a CheckSpec"
            )

    def resolve(self, reference: StandardReference) -> dict:
        self.validate_reference(reference)
        criterion = self.criteria[reference.criterion_id]
        source = self.sources[criterion.source_id]
        return {
            "source_id": source.id,
            "source_name": source.name,
            "source_type": source.type.value,
            "source_version": source.version,
            "source_url": source.url,
            "criterion_id": criterion.id,
            "criterion_title": criterion.title,
            "criterion_level": criterion.level,
            "criterion_url": criterion.url or source.url,
            "relation": reference.relation.value,
            "notes": reference.notes,
        }


class CheckSpecRegistry:
    def __init__(self, root: Path, standards: StandardsRegistry | None = None):
        self.root = root
        self.standards = standards
        self._specs: dict[str, CheckSpec] = {}

    def load(self) -> CheckSpecRegistry:
        self._specs = {
            spec.id: spec
            for path in sorted(self.root.glob("*.yaml"))
            for spec in [CheckSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))]
        }
        if self.standards:
            for spec in self._specs.values():
                if not spec.standard_refs:
                    raise ValueError(f"CheckSpec {spec.id} must reference an internal criterion")
                criterion_ids = [ref.criterion_id for ref in spec.standard_refs]
                if len(criterion_ids) != len(set(criterion_ids)):
                    raise ValueError(f"CheckSpec {spec.id} has duplicate standard references")
                for reference in spec.standard_refs:
                    self.standards.validate_reference(reference)
        return self

    def all(self) -> list[CheckSpec]:
        return list(self._specs.values())

    def get(self, check_spec_id: str) -> CheckSpec:
        return self._specs[check_spec_id]
