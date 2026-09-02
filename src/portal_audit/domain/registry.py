"""Versioned CheckSpec registry."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from portal_audit.domain.models import (
    CapabilityKind,
    CapabilityManifest,
    CheckScope,
    CheckSpec,
    JourneyDefinition,
    JourneyExecutorManifest,
    PageMapNode,
    SafetyProfile,
    StandardCriterion,
    StandardReference,
    StandardSource,
    StandardSourceStatus,
    TransitionDefinition,
)


def _load_entrypoint(entrypoint: str) -> type:
    """Load a class declared by ``package.module:ClassName``."""
    try:
        module_name, class_name = entrypoint.split(":", 1)
        return getattr(importlib.import_module(module_name), class_name)
    except (ValueError, ImportError, AttributeError) as error:
        raise ValueError(f"Invalid capability entrypoint: {entrypoint}") from error


class CapabilityRegistry:
    """Registry for deterministic and model-backed CheckSpec capabilities.

    CheckSpecs stay business-facing.  This registry owns the implementation
    binding, evidence contract and supported scope for each capability.
    """

    def __init__(self, root: Path):
        self.root = root
        self._manifests: dict[str, CapabilityManifest] = {}

    def load(self) -> CapabilityRegistry:
        manifests = [
            CapabilityManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.rglob("*.yaml"))
        ]
        StandardsRegistry._reject_duplicate_ids(manifests, "capability")
        for manifest in manifests:
            implementation = manifest.implementation
            if manifest.kind == CapabilityKind.DETERMINISTIC:
                if not implementation.entrypoint or implementation.skill_id:
                    raise ValueError(
                        f"Deterministic capability {manifest.id} requires only implementation.entrypoint"
                    )
                _load_entrypoint(implementation.entrypoint)
            else:
                if not implementation.skill_id or implementation.entrypoint:
                    raise ValueError(
                        f"Skill capability {manifest.id} requires only implementation.skill_id"
                    )
                if manifest.modality is None:
                    raise ValueError(f"Skill capability {manifest.id} requires modality")
        self._manifests = {item.id: item for item in manifests}
        return self

    def get(self, capability_id: str) -> CapabilityManifest:
        try:
            return self._manifests[capability_id]
        except KeyError as error:
            raise ValueError(f"Unknown capability: {capability_id}") from error

    def all(self) -> list[CapabilityManifest]:
        return list(self._manifests.values())

    def validate_check_spec(self, spec: CheckSpec) -> None:
        manifest = self.get(spec.executor.capability_id)
        if spec.scope not in manifest.supported_scopes:
            raise ValueError(
                f"CheckSpec {spec.id} scope={spec.scope.value} is not supported by "
                f"capability {manifest.id}"
            )
        if manifest.kind == CapabilityKind.DETERMINISTIC and spec.executor.type.value != "deterministic":
            raise ValueError(f"CheckSpec {spec.id} executor type does not match capability kind")
        if manifest.kind == CapabilityKind.SKILL and spec.executor.type.value != "model_skill":
            raise ValueError(f"CheckSpec {spec.id} executor type does not match capability kind")
        missing = set(manifest.required_evidence) - set(spec.required_evidence)
        if missing:
            raise ValueError(
                f"CheckSpec {spec.id} does not declare capability evidence: {sorted(missing)}"
            )

    def create_checker(self, capability_id: str, settings: Any | None = None) -> object:
        manifest = self.get(capability_id)
        if manifest.kind != CapabilityKind.DETERMINISTIC:
            raise ValueError(f"Capability {capability_id} is not a deterministic checker")
        implementation = manifest.implementation
        assert implementation.entrypoint is not None
        checker_type = _load_entrypoint(implementation.entrypoint)
        kwargs: dict[str, Any] = {}
        for name, value in implementation.init.items():
            if isinstance(value, str) and value.startswith("$settings."):
                if settings is None:
                    raise ValueError(f"Capability {capability_id} requires runtime settings")
                kwargs[name] = getattr(settings, value.removeprefix("$settings."))
            else:
                kwargs[name] = value
        return checker_type(**kwargs)

    def skill_id_for(self, capability_id: str) -> str:
        manifest = self.get(capability_id)
        if manifest.kind != CapabilityKind.SKILL:
            raise ValueError(f"Capability {capability_id} is not a Skill")
        assert manifest.implementation.skill_id is not None
        return manifest.implementation.skill_id


class JourneyExecutorRegistry:
    """Registry for safe Journey execution modes, separate from Check capabilities."""

    def __init__(self, root: Path):
        self.root = root
        self._manifests: dict[str, JourneyExecutorManifest] = {}

    def load(self) -> JourneyExecutorRegistry:
        manifests = [
            JourneyExecutorManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("*.yaml"))
        ]
        StandardsRegistry._reject_duplicate_ids(manifests, "journey executor")
        for manifest in manifests:
            _load_entrypoint(manifest.entrypoint)
        self._manifests = {item.id: item for item in manifests}
        return self

    def get(self, executor_id: str) -> JourneyExecutorManifest:
        try:
            return self._manifests[executor_id]
        except KeyError as error:
            raise ValueError(f"Unknown Journey executor: {executor_id}") from error

    def create(self, executor_id: str) -> object:
        manifest = self.get(executor_id)
        return _load_entrypoint(manifest.entrypoint)()


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
    def __init__(
        self,
        root: Path,
        standards: StandardsRegistry | None = None,
        capabilities: CapabilityRegistry | None = None,
    ):
        self.root = root
        self.standards = standards
        self.capabilities = capabilities
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
        for spec in self._specs.values():
            self._validate_scope(spec)
            if self.capabilities:
                self.capabilities.validate_check_spec(spec)
        return self

    @staticmethod
    def _validate_scope(spec: CheckSpec) -> None:
        transition_conditions = set(spec.applies_when).intersection(
            {"transition_ids", "from_stages", "to_archetypes"}
        )
        journey_conditions = set(spec.applies_when).intersection(
            {"journey_ids", "execution_modes"}
        )
        if spec.scope == CheckScope.PAGE and (transition_conditions or journey_conditions):
            raise ValueError(f"Page CheckSpec {spec.id} uses non-page applies_when fields")
        if spec.scope == CheckScope.TRANSITION:
            if journey_conditions:
                raise ValueError(f"Transition CheckSpec {spec.id} uses Journey conditions")
            if not transition_conditions:
                raise ValueError(f"Transition CheckSpec {spec.id} must declare applicability")
        if spec.scope == CheckScope.JOURNEY:
            if transition_conditions:
                raise ValueError(f"Journey CheckSpec {spec.id} uses Transition conditions")
            if spec.comparison is None:
                raise ValueError(f"Journey CheckSpec {spec.id} must declare comparison policy")
        elif spec.comparison is not None:
            raise ValueError(
                f"Non-Journey CheckSpec {spec.id} cannot declare comparison policy"
            )

    def all(self) -> list[CheckSpec]:
        return list(self._specs.values())

    def get(self, check_spec_id: str) -> CheckSpec:
        return self._specs[check_spec_id]


class PageMapRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._nodes: dict[str, PageMapNode] = {}

    def load(self) -> PageMapRegistry:
        nodes = [
            PageMapNode.model_validate(raw)
            for path in sorted(self.root.rglob("*.yaml"))
            for raw in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(
                "nodes", []
            )
        ]
        StandardsRegistry._reject_duplicate_ids(nodes, "PageMapNode")
        self._nodes = {item.id: item for item in nodes}
        return self

    def all(self) -> list[PageMapNode]:
        return list(self._nodes.values())

    def get(self, node_id: str) -> PageMapNode:
        return self._nodes[node_id]


class TransitionRegistry:
    def __init__(self, root: Path, page_maps: PageMapRegistry):
        self.root = root
        self.page_maps = page_maps
        self._transitions: dict[str, TransitionDefinition] = {}

    def load(self) -> TransitionRegistry:
        transitions = [
            TransitionDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("*.yaml"))
        ]
        StandardsRegistry._reject_duplicate_ids(transitions, "Transition")
        node_ids = {item.id for item in self.page_maps.all()}
        for transition in transitions:
            missing = {transition.from_node, transition.to_node} - node_ids
            if missing:
                raise ValueError(
                    f"Transition {transition.id} references unknown PageMapNode(s): "
                    f"{', '.join(sorted(missing))}"
                )
            if transition.end_condition.page_map_node != transition.to_node:
                raise ValueError(
                    f"Transition {transition.id} end_condition must reference its to node"
                )
        self._transitions = {item.id: item for item in transitions}
        return self

    def all(self) -> list[TransitionDefinition]:
        return list(self._transitions.values())

    def get(self, transition_id: str) -> TransitionDefinition:
        return self._transitions[transition_id]


class JourneyRegistry:
    def __init__(
        self,
        root: Path,
        page_maps: PageMapRegistry,
        transitions: TransitionRegistry,
    ):
        self.root = root
        self.page_maps = page_maps
        self.transitions = transitions
        self._journeys: dict[str, JourneyDefinition] = {}

    def load(self) -> JourneyRegistry:
        journeys = [
            JourneyDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("*.yaml"))
        ]
        StandardsRegistry._reject_duplicate_ids(journeys, "Journey")
        node_ids = {item.id for item in self.page_maps.all()}
        transition_ids = {item.id for item in self.transitions.all()}
        for journey in journeys:
            if journey.start not in node_ids:
                raise ValueError(f"Journey {journey.id} references unknown start node")
            missing = set(journey.transitions) - transition_ids
            if missing:
                raise ValueError(
                    f"Journey {journey.id} references unknown Transition(s): "
                    f"{', '.join(sorted(missing))}"
                )
            current = journey.start
            for transition_id in journey.transitions:
                transition = self.transitions.get(transition_id)
                if transition.from_node != current:
                    raise ValueError(
                        f"Journey {journey.id} has discontinuous transition {transition_id}"
                    )
                current = transition.to_node
        self._journeys = {item.id: item for item in journeys}
        return self

    def get(self, journey_id: str) -> JourneyDefinition:
        return self._journeys[journey_id]


class SafetyProfileRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._profiles: dict[str, SafetyProfile] = {}

    def load(self) -> SafetyProfileRegistry:
        profiles = [
            SafetyProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("*.yaml"))
        ]
        StandardsRegistry._reject_duplicate_ids(profiles, "SafetyProfile")
        self._profiles = {item.id: item for item in profiles}
        return self

    def get(self, profile_id: str) -> SafetyProfile:
        return self._profiles[profile_id]
