from itertools import pairwise

from PIL import Image

from portal_audit.adapters.browser.visual_evidence import VisualEvidenceBuilder


def test_visual_evidence_builder_emits_bounded_images_and_coordinate_metadata(tmp_path):
    full = tmp_path / "page-full.png"
    viewport = tmp_path / "page-viewport.png"
    Image.new("RGB", (1170, 6000), "white").save(full)
    Image.new("RGB", (1170, 2532), "white").save(viewport)

    artifacts = VisualEvidenceBuilder(max_tiles=3).build(
        full_page_path=full,
        viewport_path=viewport,
        document_size={"width": 390, "height": 2000},
        output_dir=tmp_path,
    )

    assert [item.kind for item in artifacts] == [
        "visual_viewport",
        "visual_overview",
        "visual_tile",
        "visual_tile",
        "visual_tile",
    ]
    assert all(item.metadata["coordinate_space"] == "document_css_px" for item in artifacts)
    assert artifacts[-1].metadata["region"]["y"] > artifacts[-2].metadata["region"]["y"]
    assert all(item.path == str(viewport) or tmp_path.joinpath(item.path).exists() for item in artifacts)


def test_visual_evidence_default_tiles_cover_full_page_without_a_total_cap(tmp_path):
    full = tmp_path / "page-full.png"
    viewport = tmp_path / "page-viewport.png"
    Image.new("RGB", (390, 6000), "white").save(full)
    Image.new("RGB", (390, 844), "white").save(viewport)

    artifacts = VisualEvidenceBuilder().build(
        full_page_path=full,
        viewport_path=viewport,
        document_size={"width": 390, "height": 6000},
        output_dir=tmp_path,
    )
    tiles = [item for item in artifacts if item.kind == "visual_tile"]
    regions = [item.metadata["region"] for item in tiles]

    assert len(tiles) > 3
    assert regions[0]["y"] == 0
    assert regions[-1]["y"] + regions[-1]["height"] >= 6000
    assert all(
        current["y"] <= previous["y"] + previous["height"]
        for previous, current in pairwise(regions)
    )
