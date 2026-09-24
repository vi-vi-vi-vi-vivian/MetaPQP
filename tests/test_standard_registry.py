from pathlib import Path

import pytest

from portal_audit.domain.models import StandardReference, StandardRelation
from portal_audit.domain.registry import CheckSpecRegistry, StandardsRegistry

ROOT = Path(__file__).parents[1]


def test_standard_catalog_validates_all_checkspec_references():
    standards = StandardsRegistry(ROOT / "config" / "standards").load()
    specs = CheckSpecRegistry(
        ROOT / "config" / "check_specs",
        standards=standards,
    ).load()

    assert len(standards.sources) == 4
    assert standards.sources["huawei-cloud-design"].status == "reserved"
    # Loading is the contract under test: every registered CheckSpec must be
    # valid against the standard catalogue.  The number deliberately evolves
    # as rules are added, so a fixed count would turn valid additions into a
    # misleading regression failure.
    assert specs.all()
    # A rule may directly implement WCAG or Nielsen without needing a duplicate
    # internal criterion.  Registry loading already validates every reference;
    # require that each registered rule declares at least one of them.
    assert all(spec.standard_refs for spec in specs.all())


def test_many_to_many_mapping_supports_multiple_specs_and_references():
    standards = StandardsRegistry(ROOT / "config" / "standards").load()
    specs = CheckSpecRegistry(
        ROOT / "config" / "check_specs",
        standards=standards,
    ).load()

    h2_specs = {
        spec.id
        for spec in specs.all()
        if any(ref.criterion_id == "nielsen-heuristics/H2" for ref in spec.standard_refs)
    }

    assert h2_specs == {
        "cta-clarity",
        "cross-stage-action-expectation-continuity",
        "journey-transition-reachability",
        "pricing-transparency",
        "product-value-clarity",
        "terminology-clarity",
        "transition-intent-result-consistency",
    }
    assert len(specs.get("document-structure").standard_refs) == 2


def test_unknown_standard_references_are_rejected():
    standards = StandardsRegistry(ROOT / "config" / "standards").load()

    with pytest.raises(ValueError, match="Unknown standard criterion"):
        standards.validate_reference(
            StandardReference(
                criterion_id="unknown/criterion",
                relation=StandardRelation.SUPPORTS,
            )
        )
