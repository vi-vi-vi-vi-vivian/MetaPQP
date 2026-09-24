"""Serializable, reviewable snapshots of requests sent to a model provider."""

from __future__ import annotations

import re

from portal_audit.application.ports.model import ImageContent, ModelRequest, TextContent


def model_request_trace(request: ModelRequest) -> dict:
    """Capture the effective prompt without duplicating binary image payloads.

    Images are already persisted as page artifacts.  Keeping their paths and
    media metadata makes a call reproducible while avoiding base64 copies in
    audit.json and the human-readable prompt document.
    """

    content = []
    for item in request.content:
        if isinstance(item, TextContent):
            content.append({"type": "text", "text": item.text})
        elif isinstance(item, ImageContent):
            content.append(
                {
                    "type": "image",
                    "artifact_ref": item.artifact_ref,
                    "media_type": item.media_type,
                    "bytes": len(item.data),
                    "width": item.width,
                    "height": item.height,
                }
            )
    return {
        "system": request.system,
        "content": content,
        "response_schema": dict(request.schema) if request.schema else None,
    }


def safe_model_error(error: Exception) -> str:
    """Return a persistable provider error without accidental credentials."""
    detail = str(error).replace("\n", " ").strip()
    detail = re.sub(
        r"(?i)(api[_-]?key|authorization|bearer)\s*([=:])\s*[^,\s]+",
        r"\1\2[REDACTED]",
        detail,
    )
    return detail[:2_000] or type(error).__name__
