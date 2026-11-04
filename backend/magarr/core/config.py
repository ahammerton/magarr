"""Configuration service.

Settings come from three layers, highest priority first:

1. Environment variables: ``MAGARR_<SECTION>__<KEY>``, e.g. ``MAGARR_LOGGING__LEVEL=DEBUG``.
2. ``<config_dir>/config.yaml``.
3. Defaults declared on the schema below.

The config directory itself is bootstrapped from ``MAGARR_CONFIG_DIR`` (default ``./config``)
because it decides where the YAML file lives. On first boot the YAML file is written with all
defaults plus a freshly generated API key, so the key survives restarts.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

CONFIG_FILE_NAME = "config.yaml"
DEFAULT_PORT = 8282

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)


class AuthSettings(BaseModel):
    api_key: str = ""
    basic_auth_enabled: bool = False
    username: str = ""
    password: str = ""

    @field_validator("api_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class LoggingSettings(BaseModel):
    level: LogLevel = "INFO"
    json_format: bool = False
    file_enabled: bool = True

    @field_validator("level", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value


class DownloadsSettings(BaseModel):
    # How often active downloads are checked in their clients.
    poll_interval: float = Field(default=30.0, ge=0.5, le=3600)


class AutomationConfig(BaseModel):
    # How often the scheduler checks whether RSS sync, backlog search or expected issues are due.
    tick_seconds: float = Field(default=60.0, ge=0.1, le=3600)
    # Length of a "minute" for the intervals set in the UI. Only tests change it, so a
    # 10-minute RSS interval can run in seconds.
    minute_seconds: float = Field(default=60.0, ge=0.01, le=60)


class DatabaseSettings(BaseModel):
    # Empty means "SQLite file in the config dir".
    url: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAGARR_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    server: ServerSettings = ServerSettings()
    auth: AuthSettings = AuthSettings()
    logging: LoggingSettings = LoggingSettings()
    database: DatabaseSettings = DatabaseSettings()
    downloads: DownloadsSettings = DownloadsSettings()
    automation: AutomationConfig = AutomationConfig()

    # Runtime-only: where config.yaml, the database and logs live. Never written to YAML.
    config_dir: Path = Field(default=Path("config"), exclude=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # YAML values are passed as init kwargs; env vars must win over them.
        return (env_settings, init_settings)

    @property
    def config_file(self) -> Path:
        return self.config_dir / CONFIG_FILE_NAME

    @property
    def log_dir(self) -> Path:
        return self.config_dir / "logs"

    @property
    def cover_cache_dir(self) -> Path:
        return self.config_dir / "cache" / "covers"

    @property
    def database_url(self) -> str:
        return self.database.url or f"sqlite:///{self.config_dir / 'magarr.db'}"


def resolve_config_dir(config_dir: Path | str | None = None) -> Path:
    raw = config_dir if config_dir is not None else os.environ.get("MAGARR_CONFIG_DIR", "config")
    return Path(raw).expanduser().resolve()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def generate_api_key() -> str:
    return secrets.token_hex(16)


def load_settings(config_dir: Path | str | None = None) -> Settings:
    """Load settings, creating config.yaml (with a generated API key) on first boot."""
    directory = resolve_config_dir(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    config_file = directory / CONFIG_FILE_NAME

    raw = _read_yaml(config_file)
    settings = Settings(**raw, config_dir=directory)

    if not config_file.exists():
        # Persist the full default schema so users can see every option. model_construct()
        # skips the env source, so env overrides are never written to disk.
        raw = Settings.model_construct().model_dump(mode="json")
    if not settings.auth.api_key:
        raw.setdefault("auth", {})["api_key"] = generate_api_key()
    if raw != _read_yaml(config_file):
        _write_yaml(config_file, raw)
        settings = Settings(**raw, config_dir=directory)

    return settings
