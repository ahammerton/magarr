from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from magarr.core.config import Settings, load_settings
from magarr.main import create_app

# Names tests may resolve; anything else fails at once, like an unknown host (no real DNS).
FAKE_DNS: dict[str, str] = {"localhost": "127.0.0.1"}


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    import ipaddress

    from magarr.core import netguard

    table = dict(FAKE_DNS)

    def lookup(host: str, port: int):
        if host not in table:
            raise OSError(f"unknown host {host}")
        return {ipaddress.ip_address(table[host])}

    monkeypatch.setattr(netguard, "lookup", lookup)
    return table


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("MAGARR_"):
            monkeypatch.delenv(key)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


@pytest.fixture
def settings(config_dir: Path) -> Settings:
    return load_settings(config_dir)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A fake built frontend."""
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>Magarr</title><div id=root>")
    (directory / "assets" / "app.js").write_text("console.log('magarr')")
    return directory


@pytest.fixture
def client(settings: Settings, dist: Path) -> Iterator[TestClient]:
    with TestClient(create_app(settings, frontend_dist=dist)) as test_client:
        yield test_client


@pytest.fixture
def api_headers(settings: Settings) -> dict[str, str]:
    return {"X-Api-Key": settings.auth.api_key}


@pytest.fixture
def api(client: TestClient, api_headers: dict[str, str]) -> TestClient:
    """A client that always sends the API key."""
    client.headers.update(api_headers)
    return client


@pytest.fixture
def library_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "library"
    directory.mkdir()
    return directory


@pytest.fixture
def root_folder(api: TestClient, library_dir: Path) -> dict:
    response = api.post("/api/v1/rootfolder", json={"path": str(library_dir)})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def magazine(api: TestClient, root_folder: dict) -> dict:
    response = api.post(
        "/api/v1/magazine",
        json={"title": "National Geographic", "frequency": "monthly", "firstIssueYear": 1888},
    )
    assert response.status_code == 201, response.text
    return response.json()
