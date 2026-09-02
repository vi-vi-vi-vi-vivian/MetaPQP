from pathlib import Path

from portal_audit.domain.registry import (
    CapabilityRegistry,
    CheckSpecRegistry,
    JourneyExecutorRegistry,
    StandardsRegistry,
)
from portal_audit.journey_executors.sequential import SequentialJourneyExecutor
from portal_audit.skill_runtime.loader import SkillLoader

ROOT = Path(__file__).parents[1]


def test_capability_manifests_validate_and_load_implementations():
    capabilities = CapabilityRegistry(ROOT / "config/capabilities").load()
    standards = StandardsRegistry(ROOT / "config/standards").load()
    CheckSpecRegistry(ROOT / "config/check_specs", standards, capabilities).load()

    checker = capabilities.create_checker("image-alt-checker")
    assert checker.id == "image-alt-checker"
    assert SkillLoader(ROOT / "skills", capabilities).load("copy-quality").name == "copy-quality"
    assert capabilities.get("visible-content-occlusion").modality.value == "vision"


def test_sequential_journey_executor_is_manifest_registered():
    registry = JourneyExecutorRegistry(ROOT / "config/journey_executors").load()

    assert registry.get("sequential").requires_supervision is True
    assert isinstance(registry.create("sequential"), SequentialJourneyExecutor)
