"""OpenRouter OpenAI-compatible structured-output adapter."""

from __future__ import annotations

import asyncio
import base64
import json
from time import monotonic
from typing import Any

import httpx

from portal_audit.application.ports.model import (
    ImageContent,
    ModelCompletion,
    ModelRequest,
    TextContent,
)

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenRouterModelAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 120,
        proxy_url: str | None = None,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 3,
        provider_name: str = "openrouter",
        max_images: int | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.proxy_url = proxy_url
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.provider_name = provider_name
        self.max_images = max_images

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def complete_json(self, request: ModelRequest) -> ModelCompletion:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        images = [item for item in request.content if isinstance(item, ImageContent)]
        if self.max_images is not None and len(images) > self.max_images:
            raise ValueError(
                f"{self.provider_name} request has {len(images)} images; "
                f"maximum is {self.max_images}"
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": self._content_parts(request)},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if request.schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "check_result",
                    "strict": True,
                    "schema": dict(request.schema),
                },
            }
        started_at = monotonic()
        response = await self._post(payload)
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
            provider=self.provider_name,
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

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy_url) as client:
            for attempt in range(1, self.retry_attempts + 1):
                try:
                    response = await client.post(
                        self.base_url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if response.status_code not in RETRYABLE_STATUS_CODES:
                        response.raise_for_status()
                        return response
                    last_error = httpx.HTTPStatusError(
                        f"retryable OpenRouter HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                except (httpx.TransportError, httpx.TimeoutException) as error:
                    last_error = error
                if attempt < self.retry_attempts:
                    await asyncio.sleep(self.retry_backoff_seconds * attempt)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _content_parts(request: ModelRequest) -> str | list[dict[str, Any]]:
        if len(request.content) == 1 and isinstance(request.content[0], TextContent):
            return request.content[0].text
        parts: list[dict[str, Any]] = []
        for item in request.content:
            if isinstance(item, TextContent):
                parts.append({"type": "text", "text": item.text})
            elif isinstance(item, ImageContent):
                encoded = base64.b64encode(item.data).decode("ascii")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{item.media_type};base64,{encoded}"},
                    }
                )
        return parts


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
