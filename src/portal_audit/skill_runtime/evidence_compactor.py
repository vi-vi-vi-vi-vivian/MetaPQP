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
    """Project a complete snapshot without silently truncating semantic evidence.

    The historical class name is retained for API compatibility. Compression here
    means removing browser-only fields, never taking a prefix of page evidence.
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
        elements = []
        included_refs: set[str] = set()
        for order, item in enumerate(snapshot.evidence_elements, start=1):
            included_refs.add(item.element_ref)
            element = {
                "element_ref": item.element_ref,
                "order": order,
                "tag": item.tag,
                "text": item.text,
                "interactive": item.element_ref in interactive_refs,
            }
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
                element.update(
                    {
                        "role": item.role,
                        "href": item.href,
                        "accessible_name": item.accessible_name,
                        "enabled": item.enabled,
                    }
                )
            if profile == "transaction_evidence" and (
                item.element_ref in interactive_refs or item.interactive_ancestor
            ):
                element.update(
                    {
                        "interactive_ancestor": item.interactive_ancestor,
                    }
                )
            elements.append(element)

        next_order = len(elements) + 1
        for item in snapshot.interactive_elements:
            if item.element_ref is None or item.element_ref in included_refs:
                continue
            elements.append(
                {
                    "element_ref": item.element_ref,
                    "order": next_order,
                    "tag": item.tag,
                    "role": item.role,
                    "text": item.text,
                    "href": item.href,
                    "alt": None,
                    "has_alt": None,
                    "accessible_name": "",
                    "surrounding_text": "",
                    "interactive_ancestor": False,
                    "enabled": item.enabled,
                    "interactive": True,
                }
            )
            next_order += 1

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
                    "evidence_elements": len(snapshot.evidence_elements),
                    "interactive_elements": len(interactive_refs),
                    "images": sum(1 for item in snapshot.evidence_elements if item.tag == "img"),
                },
            },
        }
