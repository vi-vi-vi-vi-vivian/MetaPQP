"""Build bounded image evidence for visual model checks."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from portal_audit.domain.models import ArtifactRef


class VisualEvidenceBuilder:
    def __init__(self, *, max_tiles: int | None = None):
        # ``max_tiles`` remains as an explicit compatibility/testing override.
        # The production default is unlimited and covers the page continuously.
        self.max_tiles = max_tiles

    def build(
        self,
        *,
        full_page_path: Path,
        viewport_path: Path,
        document_size: dict[str, int],
        output_dir: Path,
    ) -> list[ArtifactRef]:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = [
            ArtifactRef(
                kind="visual_viewport",
                path=str(viewport_path),
                media_type="image/png",
                metadata={
                    "coordinate_space": "document_css_px",
                    "region": {
                        "x": 0,
                        "y": 0,
                        "width": document_size.get("width", 0),
                        "height": min(
                            document_size.get("height", 0),
                            round(document_size.get("width", 0) * 844 / 390),
                        ),
                    },
                },
            )
        ]
        with Image.open(full_page_path) as source:
            source = source.convert("RGB")
            overview = source.copy()
            overview.thumbnail((1200, 1800))
            overview_path = output_dir / "visual-overview.jpg"
            overview.save(overview_path, "JPEG", quality=82, optimize=True)
            artifacts.append(
                ArtifactRef(
                    kind="visual_overview",
                    path=str(overview_path),
                    media_type="image/jpeg",
                    metadata={
                        "coordinate_space": "document_css_px",
                        "region": {
                            "x": 0,
                            "y": 0,
                            "width": document_size.get("width", 0),
                            "height": document_size.get("height", 0),
                        },
                    },
                )
            )
            artifacts.extend(
                self._tiles(source, document_size=document_size, output_dir=output_dir)
            )
        return artifacts

    def _tiles(
        self, source: Image.Image, *, document_size: dict[str, int], output_dir: Path
    ) -> list[ArtifactRef]:
        if self.max_tiles == 0:
            return []
        crop_height = min(source.height, round(source.width * 844 / 390))
        tops = list(range(0, source.height, crop_height)) or [0]
        last_top = max(0, source.height - crop_height)
        if tops[-1] != last_top:
            tops.append(last_top)
        tops = list(dict.fromkeys(tops))
        if self.max_tiles is not None:
            tops = tops[: max(0, self.max_tiles)]
        css_x_scale = document_size.get("width", 0) / source.width if source.width else 1
        css_y_scale = document_size.get("height", 0) / source.height if source.height else 1
        artifacts: list[ArtifactRef] = []
        for index, top in enumerate(tops, start=1):
            tile = source.crop((0, top, source.width, top + crop_height))
            if tile.width > 900:
                tile = tile.resize((900, round(tile.height * 900 / tile.width)))
            path = output_dir / f"visual-tile-{index}.jpg"
            tile.save(path, "JPEG", quality=86, optimize=True)
            artifacts.append(
                ArtifactRef(
                    kind="visual_tile",
                    path=str(path),
                    media_type="image/jpeg",
                    metadata={
                        "coordinate_space": "document_css_px",
                        "region": {
                            "x": 0,
                            "y": round(top * css_y_scale, 2),
                            "width": round(source.width * css_x_scale, 2),
                            "height": round(crop_height * css_y_scale, 2),
                        },
                    },
                )
            )
        return artifacts
