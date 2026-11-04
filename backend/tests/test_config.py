from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from magarr.core.config import DEFAULT_PORT, load_settings


def test_first_boot_writes_config_with_api_key(config_dir: Path) -> None:
    settings = load_settings(config_dir)

    assert settings.config_file.exists()
    data = yaml.safe_load(settings.config_file.read_text())
    assert data["auth"]["api_key"] == settings.auth.api_key
    assert len(settings.auth.api_key) == 32
    assert data["server"]["port"] == DEFAULT_PORT
    assert "config_dir" not in data


def test_config_persists_across_restarts(config_dir: Path) -> None:
    first = load_settings(config_dir)
    second = load_settings(config_dir)
    assert first.auth.api_key == second.auth.api_key


def test_yaml_values_are_used(config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "logging:\n  level: debug\n  json_format: true\nauth:\n  api_key: abc123abc123abc123\n"
    )
    settings = load_settings(config_dir)
    assert settings.logging.level == "DEBUG"
    assert settings.logging.json_format is True
    assert settings.auth.api_key == "abc123abc123abc123"
    # A user-written partial file is left as the user wrote it.
    assert "server" not in yaml.safe_load((config_dir / "config.yaml").read_text())


def test_env_overrides_yaml_and_merges_nested(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "logging:\n  level: INFO\n  json_format: true\nauth:\n  api_key: fromyamlfromyaml\n"
    )
    monkeypatch.setenv("MAGARR_LOGGING__LEVEL", "WARNING")
    monkeypatch.setenv("MAGARR_SERVER__PORT", "9000")

    settings = load_settings(config_dir)

    assert settings.logging.level == "WARNING"
    assert settings.logging.json_format is True  # untouched yaml sibling survives
    assert settings.server.port == 9000
    # Env overrides are not written back to the file.
    assert yaml.safe_load((config_dir / "config.yaml").read_text())["logging"]["level"] == "INFO"


def test_env_api_key_skips_generation(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGARR_AUTH__API_KEY", "envkeyenvkeyenvkey")
    settings = load_settings(config_dir)
    assert settings.auth.api_key == "envkeyenvkeyenvkey"


def test_config_dir_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGARR_CONFIG_DIR", str(tmp_path / "elsewhere"))
    settings = load_settings()
    assert settings.config_dir == (tmp_path / "elsewhere").resolve()
    assert settings.database_url.endswith("elsewhere/magarr.db")


def test_invalid_values_are_rejected(config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("logging:\n  level: LOUD\n")
    with pytest.raises(ValidationError):
        load_settings(config_dir)


def test_non_mapping_yaml_is_rejected(config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("- just\n- a list\n")
    with pytest.raises(ValueError, match="mapping"):
        load_settings(config_dir)


def test_first_boot_does_not_persist_env_overrides(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAGARR_SERVER__PORT", "9000")
    settings = load_settings(config_dir)
    assert settings.server.port == 9000
    assert yaml.safe_load(settings.config_file.read_text())["server"]["port"] == DEFAULT_PORT
