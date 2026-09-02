import base64
import json
from io import BytesIO
from types import SimpleNamespace

import requests
from PIL import Image

from portal_audit.adapters.models.gemini import GeminiModelAdapter
from portal_audit.application.ports.model import ImageContent, ModelRequest, TextContent


class FakeInteractions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="interaction-1",
            model="gemini-3.7-flash",
            output_text=json.dumps({"status": "pass"}),
            usage=SimpleNamespace(
                total_input_tokens=120,
                total_output_tokens=12,
                total_tokens=132,
            ),
        )


async def test_gemini_adapter_maps_provider_neutral_multimodal_request():
    interactions = FakeInteractions()
    client = SimpleNamespace(interactions=interactions)
    adapter = GeminiModelAdapter(api_key=None, client=client)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string"},
            "detail": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"reason": {"type": "string"}},
            },
        },
        "required": ["status"],
    }

    completion = await adapter.complete_json(
        ModelRequest(
            system="Follow the audit contract.",
            content=[
                TextContent("page evidence"),
                ImageContent(
                    data=b"image-bytes",
                    media_type="image/png",
                    artifact_ref="viewport.png",
                ),
            ],
            schema=schema,
        )
    )

    assert completion.provider == "google-gemini"
    assert completion.content == {"status": "pass"}
    assert completion.total_tokens == 132
    assert interactions.kwargs["model"] == "gemini-3.7-flash"
    assert interactions.kwargs["input"][2]["type"] == "image"
    assert interactions.kwargs["response_format"]["schema"] == schema


def test_gemini_adapter_compresses_large_inline_images():
    raw = BytesIO()
    Image.new("RGB", (1600, 1600), "white").save(raw, "PNG")
    adapter = GeminiModelAdapter(
        api_key="configured",
        image_compress_threshold_bytes=1,
        image_max_pixels=1_000_000,
        image_jpeg_quality=82,
    )

    media_type, encoded = adapter._encoded_image(
        ImageContent(
            data=raw.getvalue(),
            media_type="image/png",
            artifact_ref="large.png",
        )
    )

    compressed = base64.b64decode(encoded)
    with Image.open(BytesIO(compressed)) as image:
        assert media_type == "image/jpeg"
        assert image.width * image.height <= 1_000_000
    assert len(compressed) < len(raw.getvalue())


class FakeGenerateContentResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}",
                response=self,
            )


async def test_gemini_adapter_uses_generate_content_with_proxy(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeGenerateContentResponse(
            payload={
                "responseId": "response-1",
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": json.dumps({"status": "pass"})}]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 12,
                    "totalTokenCount": 132,
                },
            }
        )

    monkeypatch.setattr(
        "portal_audit.adapters.models.gemini.requests.post",
        fake_post,
    )
    proxy = "http://127.0.0.1:15236"
    adapter = GeminiModelAdapter(
        api_key="test-key",
        proxy_url=proxy,
        retry_attempts=1,
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string"},
            "detail": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"reason": {"type": "string"}},
            },
        },
        "required": ["status"],
    }

    completion = await adapter.complete_json(
        ModelRequest(
            system="Follow the audit contract.",
            content=[
                TextContent("page evidence"),
                ImageContent(
                    data=b"image-bytes",
                    media_type="image/png",
                    artifact_ref="viewport.png",
                ),
            ],
            schema=schema,
        )
    )

    assert captured["url"].endswith("/gemini-3.7-flash:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["proxies"] == {"http": proxy, "https": proxy}
    transported_schema = captured["json"]["generationConfig"]["responseSchema"]
    assert "additionalProperties" not in transported_schema
    assert "additionalProperties" not in transported_schema["properties"]["detail"]
    assert transported_schema["required"] == ["status"]
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[-1]["inlineData"]["mimeType"] == "image/png"
    assert completion.provider_request_id == "response-1"
    assert completion.total_tokens == 132


async def test_gemini_adapter_falls_back_after_rate_limit(monkeypatch):
    urls = []

    def fake_post(url, **kwargs):
        del kwargs
        urls.append(url)
        if "primary-model" in url:
            return FakeGenerateContentResponse(status_code=429)
        return FakeGenerateContentResponse(
            payload={
                "candidates": [
                    {"content": {"parts": [{"text": '{"status":"pass"}'}]}}
                ]
            }
        )

    monkeypatch.setattr(
        "portal_audit.adapters.models.gemini.requests.post",
        fake_post,
    )
    adapter = GeminiModelAdapter(
        api_key="test-key",
        model="primary-model",
        fallback_models=["fallback-model"],
        retry_attempts=2,
        retry_backoff_seconds=0,
    )

    completion = await adapter.complete_json(
        ModelRequest(system="system", content=[TextContent("evidence")])
    )

    assert len(urls) == 2
    assert "primary-model" in urls[0]
    assert "fallback-model" in urls[1]
    assert completion.model == "fallback-model"


async def test_gemini_adapter_falls_back_immediately_after_transport_timeout(
    monkeypatch,
):
    urls = []
    timeouts = []

    def fake_post(url, **kwargs):
        urls.append(url)
        timeouts.append(kwargs["timeout"])
        if "primary-model" in url:
            raise requests.ReadTimeout("primary timed out")
        return FakeGenerateContentResponse(
            payload={
                "candidates": [
                    {"content": {"parts": [{"text": '{"status":"pass"}'}]}}
                ]
            }
        )

    monkeypatch.setattr(
        "portal_audit.adapters.models.gemini.requests.post",
        fake_post,
    )
    adapter = GeminiModelAdapter(
        api_key="test-key",
        model="primary-model",
        fallback_models=["fallback-model"],
        timeout=180,
        fallback_probe_timeout=7,
        retry_attempts=2,
        retry_backoff_seconds=0,
    )

    completion = await adapter.complete_json(
        ModelRequest(system="system", content=[TextContent("evidence")])
    )

    assert len(urls) == 2
    assert "primary-model" in urls[0]
    assert "fallback-model" in urls[1]
    assert timeouts == [7, 180]
    assert completion.model == "fallback-model"
