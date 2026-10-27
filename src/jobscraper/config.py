"""Configuration loading.

Secrets and deployment values come from ``config/config.yaml`` (gitignored, §11.2).
Non-secret tuning lives in the other YAML files under ``config/``:

- ``sources.yaml``       per-source enable flag, throttle and adapter options
- ``tech_keywords.yaml`` allow/deny lists for the tech filter (§6.2)
- ``tech_tags.yaml``     tag vocabulary
- ``locations.yaml``     city/postcode → canton, border towns

``JOBS_CONFIG_DIR`` overrides the config directory (default ``./config``).
Any value can also be overridden by env vars prefixed ``JOBS_`` with ``__`` as
nested delimiter, e.g. ``JOBS_TELEGRAM__CHAT_ID``.
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


def config_dir() -> Path:
    return Path(os.environ.get("JOBS_CONFIG_DIR", "config"))


class ProxyConfig(BaseModel):
    enabled: bool = False
    url: str | None = None
    username: str | None = None
    password: SecretStr | None = None
    # Where Selenium's Chrome sends traffic: the local forwarding proxy that adds
    # upstream credentials (§5.1). Chrome cannot authenticate itself.
    browser_url: str | None = "http://egress:3128"

    def httpx_proxy(self) -> str | None:
        """Upstream proxy URL with credentials embedded, for httpx."""
        if not self.enabled or not self.url:
            return None
        if not self.username:
            return self.url
        parts = urlsplit(self.url)
        password = self.password.get_secret_value() if self.password else ""
        auth = f"{quote(self.username, safe='')}:{quote(password, safe='')}@"
        return f"{parts.scheme}://{auth}{parts.netloc}{parts.path}"

    def describe(self) -> str:
        """Safe-to-log egress description (host only, never credentials)."""
        if not self.enabled or not self.url:
            return "direct"
        parts = urlsplit(self.url)
        return f"proxy {parts.hostname}:{parts.port}" if parts.port else f"proxy {parts.hostname}"


class TelegramConfig(BaseModel):
    bot_token: SecretStr | None = None
    # One private chat for both job messages and ⚠️ alerts (D15).
    chat_id: str | None = None
    seconds_between_messages: float = 1.0
    use_proxy: bool = False
    api_base: str = "https://api.telegram.org"


class ThrottleConfig(BaseModel):
    default_seconds_per_request: float = 2.0


class TimeoutConfig(BaseModel):
    per_source_minutes: float = 15
    global_minutes: float = 60
    request_seconds: float = 30
    page_load_seconds: float = 30


class RetentionConfig(BaseModel):
    raw_days: int = 90         # §15
    inactive_days: int = 365   # D18


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOBS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://jobs:jobs@localhost:5432/jobs"
    contact_email: str = "you@example.com"
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    throttle: ThrottleConfig = Field(default_factory=ThrottleConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    # Per-source secrets, e.g. {"foorilla": "<api key>"}.
    api_keys: dict[str, SecretStr] = Field(default_factory=dict)
    batch_size: int = 200
    closure_missed_runs: int = 3

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_source = YamlConfigSettingsSource(settings_cls, yaml_file=config_dir() / "config.yaml")
        return (init_settings, env_settings, yaml_source)

    @property
    def user_agent(self) -> str:
        return f"swiss-tech-jobs/0.1 (+mailto:{self.contact_email})"

    def api_key(self, source: str) -> str | None:
        key = self.api_keys.get(source)
        return key.get_secret_value() if key else None


class SourceConfig(BaseModel):
    enabled: bool = True
    seconds_per_request: float | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class Vocab:
    """Lazily loaded non-secret YAML files (keywords, tags, locations, sources)."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or config_dir()

    def _load(self, name: str) -> dict[str, Any]:
        path = self.directory / name
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    @cached_property
    def sources(self) -> dict[str, SourceConfig]:
        raw = self._load("sources.yaml").get("sources", {})
        return {name: SourceConfig.model_validate(cfg or {}) for name, cfg in raw.items()}

    @cached_property
    def tech_keywords(self) -> dict[str, Any]:
        return self._load("tech_keywords.yaml")

    @cached_property
    def tech_tags(self) -> dict[str, list[str]]:
        return self._load("tech_tags.yaml").get("tags", {})

    @cached_property
    def locations(self) -> dict[str, Any]:
        return self._load("locations.yaml")


def load_settings() -> Settings:
    return Settings()
