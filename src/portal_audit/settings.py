"""Runtime settings loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_root: Path = PROJECT_ROOT
    output_root: Path = PROJECT_ROOT / "output"
    data_root: Path = PROJECT_ROOT / "data"
    config_root: Path = PROJECT_ROOT / "config"
    skills_root: Path = PROJECT_ROOT / "skills"
    workflow_timeout_seconds: float = 300
    openjiuwen_log_level: str = "WARNING"
    openjiuwen_console_logs: bool = False

    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "openai/gpt-5.6-sol"
    text_model_profile: str = "default-text"
    text_model_provider: str = "openrouter"
    text_model_base_url: str | None = None
    text_model_api_key: SecretStr | None = None
    text_model_name: str | None = None
    vision_model_provider: str = "gemini"
    vision_model_base_url: str | None = None
    vision_model_api_key: SecretStr | None = None
    vision_model_name: str | None = None
    model_https_proxy: str | None = None
    model_retry_attempts: int = 2
    model_retry_backoff_seconds: float = 3

    visual_audit_enabled: bool = True
    visual_model_profile: str = "default-vision"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.7-flash"
    gemini_fallback_models: str = "gemini-3.6-flash"
    gemini_timeout_seconds: float = 180
    gemini_fallback_probe_timeout_seconds: float = 45
    gemini_image_compress_threshold_bytes: int = 250_000
    gemini_image_max_pixels: int = 1_800_000
    gemini_image_jpeg_quality: int = 82
    visual_model_max_images_per_call: int = 5

    browser_headless: bool = True
    browser_timeout_ms: int = 60_000
    browser_max_links: int = 20

    auth_account_config_path: Path = PROJECT_ROOT / "config" / "auth" / "account.local.yaml"
    huaweicloud_auth_timeout_ms: int = 60_000
    huaweicloud_login_headless: bool = True

    mcp_enabled: bool = False
    mcp_server_url: str | None = None
