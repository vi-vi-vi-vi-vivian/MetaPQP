"""Load the single local authentication account from YAML.

The application consumes one ``AuthAccount`` today. A future multi-account
registry can implement the same credential-source boundary without changing
Baseline Collector or browser acquisition.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from portal_audit.application.ports.auth import AuthAccount


class AccountConfigError(ValueError):
    """Raised for missing or invalid local account configuration."""


class SingleAccountDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    account_type: str
    provider: str = "huaweicloud"
    enabled: bool = True
    site: str = "cn"
    username: str | None = None
    password: SecretStr | None = None


class SingleAccountFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "1"
    account: SingleAccountDefinition


class YamlAccountCredentialSource:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AuthAccount:
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AccountConfigError(f"account config not found: {self.path}") from exc
        except (OSError, yaml.YAMLError) as exc:
            raise AccountConfigError(f"cannot read account config: {self.path}") from exc
        try:
            config = SingleAccountFile.model_validate(raw)
        except ValidationError as exc:
            raise AccountConfigError(f"invalid account config: {self.path}: {exc}") from exc
        account = config.account
        return AuthAccount(
            account_id=account.id,
            account_type=account.account_type,
            provider=account.provider,
            username=account.username or None,
            password=account.password.get_secret_value() if account.password else None,
            site=account.site,
            enabled=account.enabled,
        )
