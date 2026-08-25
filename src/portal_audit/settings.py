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

    browser_headless: bool = True
    browser_timeout_ms: int = 60_000
    browser_max_links: int = 20

    auth_account_config_path: Path = PROJECT_ROOT / "config" / "auth" / "account.local.yaml"
    huaweicloud_auth_timeout_ms: int = 60_000
    huaweicloud_login_headless: bool = True

    mcp_enabled: bool = False
    mcp_server_url: str | None = None
