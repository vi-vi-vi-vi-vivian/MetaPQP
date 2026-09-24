"""Build complete, provider-neutral evidence projections for model checks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, ClassVar

from portal_audit.domain.models import CheckSpec, PageSnapshot


class EvidenceContractError(ValueError):
    """Raised when a projection cannot satisfy a CheckSpec evidence contract."""


class EvidenceContractValidator:
    """Validate declared CheckSpec evidence against projection capabilities."""

    aliases: ClassVar[dict[str, str]] = {
        "title": "title",
        "headings": "headings",
        "visible_text": "visible_text",
        "interactive_elements": "interactive_elements",
        "evidence_elements": "evidence_elements",
        "surrounding_content": "surrounding_content",
        "visual_viewport": "visual_artifacts",
        "visual_overview": "visual_artifacts",
        "visual_tiles": "visual_artifacts",
        "element_bounds": "layout_metrics",
        "element_overflow_metrics": "layout_metrics",
        "mobile_layout": "mobile_layout",
    }

    def validate(self, specs: list[CheckSpec], projection: dict[str, Any]) -> None:
        available = set(projection["coverage"]["capabilities"])
        missing: dict[str, list[str]] = {}
        for spec in specs:
            unresolved = [
                item
                for item in spec.required_evidence
                if self.aliases.get(item, item) not in available
            ]
            if unresolved:
                missing[spec.id] = unresolved
        if missing:
            raise EvidenceContractError(f"Evidence contract is incomplete: {missing}")


class ModelEvidenceCompactor:
    """Project complete, locatable page evidence with no browser-shell noise.

    Raw browser evidence remains in the snapshot artifacts.  This projection is
    deliberately smaller: it excludes shared page chrome, removes null/default
    metadata, and keeps the real ``element_ref`` for every remaining item.
    """

    version = "2.0.0"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def compact(self, snapshot: PageSnapshot, profile: str = "content_evidence") -> dict[str, Any]:
        cache_key = (snapshot.snapshot_id, profile)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build(snapshot, profile)
        return deepcopy(self._cache[cache_key])

    def _build(self, snapshot: PageSnapshot, profile: str) -> dict[str, Any]:
        interactive_refs = {
            item.element_ref
            for item in snapshot.interactive_elements
            if item.element_ref is not None
        }
        content_items = [
            item
            for item in snapshot.evidence_elements
            if item.page_region not in {"header", "footer", "navigation"}
        ]
        duplicate_interactive_text = {
            item.text.strip()
            for item in content_items
            if item.element_ref in interactive_refs and item.text.strip()
            and sum(
                other.element_ref in interactive_refs
                and other.text.strip() == item.text.strip()
                for other in content_items
            ) > 1
        }
        elements = []
        included_refs: set[str] = set()
        for item in content_items:
            # Empty structural wrappers cannot support a text, CTA, pricing, or
            # terminology finding.  Images and controls remain locatable even
            # when they do not have visible text.
            is_interactive = item.element_ref in interactive_refs
            if not item.text.strip() and item.tag != "img" and not is_interactive:
                continue
            included_refs.add(item.element_ref)
            element = {
                "element_ref": item.element_ref,
                "text": item.text,
            }
            if is_interactive:
                element["interactive"] = True
            if item.tag in {"img", "a", "button", "input", "select", "textarea", "summary"}:
                element["tag"] = item.tag
            if item.tag == "img":
                element.update(
                    {
                        "alt": item.alt,
                        "has_alt": item.has_alt,
                        "accessible_name": item.accessible_name,
                        "interactive_ancestor": item.interactive_ancestor,
                    }
                )
            if profile in {"transaction_evidence", "visual"}:
                if item.role:
                    element["role"] = item.role
                if item.href:
                    element["href"] = item.href
                if item.accessible_name and item.accessible_name != item.text:
                    element["accessible_name"] = item.accessible_name
                if not item.enabled:
                    element["enabled"] = False
            if (
                profile == "transaction_evidence"
                and is_interactive
                and item.text.strip() in duplicate_interactive_text
                and item.surrounding_text.strip()
            ):
                # Duplicate CTA labels are otherwise impossible to distinguish.
                # A short nearby context is enough; the complete raw context is
                # preserved only in the local snapshot artifact.
                element["context"] = item.surrounding_text.strip()[:240]
            elements.append(element)

        for item in snapshot.interactive_elements:
            if (
                item.element_ref is None
                or item.element_ref in included_refs
                or item.page_region in {"header", "footer", "navigation"}
            ):
                continue
            elements.append(
                {
                    "element_ref": item.element_ref,
                    "text": item.text,
                    "interactive": True,
                }
            )
            if item.tag in {"a", "button", "input", "select", "textarea", "summary"}:
                elements[-1]["tag"] = item.tag
            if profile in {"transaction_evidence", "visual"}:
                if item.role:
                    elements[-1]["role"] = item.role
                if item.href:
                    elements[-1]["href"] = item.href
                if not item.enabled:
                    elements[-1]["enabled"] = False

        capabilities = {
            "title",
            "headings",
            "visible_text",
            "interactive_elements",
            "evidence_elements",
            "surrounding_content",
        }
        if profile == "visual":
            capabilities.update({"visual_artifacts", "layout_metrics", "mobile_layout"})

        return {
            "profile": profile,
            "projection_version": self.version,
            "url": snapshot.final_url,
            "title": snapshot.title,
            "headings": snapshot.headings,
            "visible_text": snapshot.body_text,
            "elements": elements,
            "coverage": {
                "status": "complete",
                "truncated": False,
                "capabilities": sorted(capabilities),
                "source_counts": {
                    "body_chars": len(snapshot.body_text),
                    "headings": len(snapshot.headings),
                    "evidence_elements": len(snapshot.evidence_elements),
                    "interactive_elements": len(snapshot.interactive_elements),
                    "images": sum(1 for item in snapshot.evidence_elements if item.tag == "img"),
                },
                "included_counts": {
                    "body_chars": len(snapshot.body_text),
                    "headings": len(snapshot.headings),
                    "evidence_elements": len(elements),
                    "interactive_elements": sum(1 for item in elements if item.get("interactive")),
                    "images": sum(1 for item in elements if item.get("tag") == "img"),
                },
            },
        }
