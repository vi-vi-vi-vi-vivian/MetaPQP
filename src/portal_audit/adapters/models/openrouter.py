"""OpenRouter OpenAI-compatible structured-output adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from time import monotonic
from typing import Any

import httpx

from portal_audit.application.ports.model import ModelCompletion


class OpenRouterModelAdapter:
    def __init__(self, *, base_url: str, api_key: str | None, model: str, timeout: float = 120):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any] | None = None,
    ) -> ModelCompletion:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "check_result", "strict": True, "schema": dict(schema)},
            }
        started_at = monotonic()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        response_payload = response.json()
        content = response_payload["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            parsed = content
        else:
            text = str(content).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(text)
        usage = response_payload.get("usage") or {}
        return ModelCompletion(
            content=parsed,
            model=str(response_payload.get("model") or self.model),
            provider_request_id=response_payload.get("id"),
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            total_tokens=_optional_int(usage.get("total_tokens")),
            latency_ms=round((monotonic() - started_at) * 1000),
            usage_details={
                key: value
                for key, value in usage.items()
                if key not in {"prompt_tokens", "completion_tokens", "total_tokens"}
            },
        )


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
