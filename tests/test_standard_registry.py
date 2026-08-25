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
    assert len(specs.all()) == 14
    assert all(
        any(ref.criterion_id.startswith("metapqp-internal/") for ref in spec.standard_refs)
        for spec in specs.all()
    )


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
        "pricing-transparency",
        "product-value-clarity",
        "terminology-clarity",
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
