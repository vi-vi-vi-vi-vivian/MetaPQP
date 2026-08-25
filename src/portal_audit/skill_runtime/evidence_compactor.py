"""Build semantically lossless, model-facing evidence without browser-only metadata."""

from __future__ import annotations

from typing import Any

from portal_audit.domain.models import PageSnapshot


class ModelEvidenceCompactor:
    """Remove local positioning data while preserving page semantics and order."""

    def compact(self, snapshot: PageSnapshot) -> dict[str, Any]:
        interactive_refs = {
            item.element_ref
            for item in snapshot.interactive_elements[:100]
            if item.element_ref is not None
        }
        elements = []
        included_refs: set[str] = set()
        for order, item in enumerate(snapshot.evidence_elements[:500], start=1):
            included_refs.add(item.element_ref)
            elements.append(
                {
                    "element_ref": item.element_ref,
                    "order": order,
                    "tag": item.tag,
                    "role": item.role,
                    "text": item.text,
                    "href": item.href,
                    "alt": item.alt,
                    "has_alt": item.has_alt,
                    "accessible_name": item.accessible_name,
                    "surrounding_text": item.surrounding_text,
                    "interactive_ancestor": item.interactive_ancestor,
                    "enabled": item.enabled,
                    "interactive": item.element_ref in interactive_refs,
                }
            )

        # Preserve interactive semantics if a browser adapter ever emits an
        # interactive element outside the general evidence collection.
        next_order = len(elements) + 1
        for item in snapshot.interactive_elements[:100]:
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
                    "enabled": item.enabled,
                    "interactive": True,
                }
            )
            next_order += 1

        return {
            "url": snapshot.final_url,
            "title": snapshot.title,
            "visible_text": snapshot.body_text[:16000],
            "elements": elements,
        }
