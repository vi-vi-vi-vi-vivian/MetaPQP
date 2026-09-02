"""Provider-neutral structured model inference port."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class TextContent:
    text: str


@dataclass(frozen=True)
class ImageContent:
    data: bytes
    media_type: str
    artifact_ref: str
    width: int | None = None
    height: int | None = None


ModelContent = TextContent | ImageContent


@dataclass(frozen=True)
class ModelRequest:
    system: str
    content: Sequence[ModelContent]
    schema: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ModelCompletion:
    content: Mapping[str, Any]
    provider: str
    model: str
    provider_request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    usage_details: Mapping[str, Any] = field(default_factory=dict)


class ModelPort(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def complete_json(self, request: ModelRequest) -> ModelCompletion: ...
