"""Conservative local verification for visual-model findings."""

from __future__ import annotations

from portal_audit.domain.models import CheckRun, CheckStatus, EvidenceElement, PageSnapshot


class VisualFindingVerifier:
    minimum_confidence = 0.8

    def verify(self, run: CheckRun, snapshot: PageSnapshot) -> CheckRun:
        if run.status != CheckStatus.FAIL:
            return run
        confirmed = run.confidence >= self.minimum_confidence and self._confirmed(run, snapshot)
        if confirmed:
            return run
        return run.model_copy(
            update={
                "status": CheckStatus.NEEDS_VERIFICATION,
                "reason": (
                    f"{run.reason}（视觉模型发现尚未通过本地几何/溢出证据复核，需人工确认）"
                ),
            }
        )

    def _confirmed(self, run: CheckRun, snapshot: PageSnapshot) -> bool:
        elements = self._matched_elements(run, snapshot)
        if run.check_spec_id == "text-clipping-and-truncation":
            return any(self._accidentally_clipped(item) for item in elements)
        if run.check_spec_id == "visible-content-occlusion":
            return self._has_overlap(elements, require_positioned=True)
        if run.check_spec_id == "responsive-visual-integrity":
            return bool(snapshot.mobile_layout and snapshot.mobile_layout.overflow_elements) or self._has_overlap(
                elements, require_positioned=False
            )
        return False

    @staticmethod
    def _matched_elements(run: CheckRun, snapshot: PageSnapshot) -> list[EvidenceElement]:
        refs = {location.element_ref for location in run.locations}
        return [item for item in snapshot.evidence_elements if item.element_ref in refs]

    @staticmethod
    def _accidentally_clipped(item: EvidenceElement) -> bool:
        style = item.computed_style
        horizontal = (
            item.scroll_width is not None
            and item.client_width is not None
            and item.scroll_width > item.client_width + 1
            and style.get("overflow_x") in {"hidden", "clip"}
        )
        vertical = (
            item.scroll_height is not None
            and item.client_height is not None
            and item.scroll_height > item.client_height + 1
            and style.get("overflow_y") in {"hidden", "clip"}
        )
        intentional = style.get("text_overflow") == "ellipsis" or style.get(
            "webkit_line_clamp"
        ) not in {None, "", "none", "0"}
        return (horizontal or vertical) and not intentional

    @classmethod
    def _has_overlap(cls, elements: list[EvidenceElement], *, require_positioned: bool) -> bool:
        for index, first in enumerate(elements):
            for second in elements[index + 1 :]:
                if require_positioned and not any(
                    item.computed_style.get("position") in {"fixed", "sticky", "absolute"}
                    for item in (first, second)
                ):
                    continue
                if cls._overlap_area(first.bounds, second.bounds) >= 400:
                    return True
        return False

    @staticmethod
    def _overlap_area(first: dict | None, second: dict | None) -> float:
        if not first or not second:
            return 0
        width = max(
            0,
            min(first["x"] + first["width"], second["x"] + second["width"])
            - max(first["x"], second["x"]),
        )
        height = max(
            0,
            min(first["y"] + first["height"], second["y"] + second["height"])
            - max(first["y"], second["y"]),
        )
        return width * height
