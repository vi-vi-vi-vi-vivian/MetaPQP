"""Structured model inference port."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelCompletion:
    content: Mapping[str, Any]
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

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any] | None = None,
    ) -> ModelCompletion: ...
