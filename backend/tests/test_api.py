import base64

from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from magarr import __version__
from magarr.core.config import Settings
from magarr.core.db import alembic_config
from magarr.main import create_app


def test_health_is_open(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_requires_api_key(client: TestClient) -> None:
    assert client.get("/api/v1/system/status").status_code == 401
    assert client.get("/api/v1/system/status", headers={"X-Api-Key": "wrong"}).status_code == 401


def test_status_accepts_header_or_query_key(client: TestClient, settings: Settings) -> None:
    key = settings.auth.api_key
    assert client.get("/api/v1/system/status", headers={"X-Api-Key": key}).status_code == 200
    assert client.get(f"/api/v1/system/status?apikey={key}").status_code == 200


def test_status_payload(client: TestClient, api_headers: dict[str, str]) -> None:
    body = client.get("/api/v1/system/status", headers=api_headers).json()
    assert body["appName"] == "Magarr"
    assert body["version"] == __version__
    assert body["databaseType"] == "sqlite"
    assert (
        body["databaseMigration"]
        == ScriptDirectory.from_config(alembic_config()).get_current_head()
    )
    assert body["authentication"] == "apiKey"
    assert body["uptimeSeconds"] >= 0
    assert set(body) >= {"startTime", "osName", "pythonVersion", "appDataDir", "isDocker"}


def test_initialize_returns_api_key(client: TestClient, settings: Settings) -> None:
    body = client.get("/initialize.json").json()
    assert body["apiKey"] == settings.auth.api_key
    assert body["version"] == __version__


def test_openapi_docs_are_open(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_unknown_api_route_is_json_404_not_spa(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/nope", headers=api_headers)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_spa_serves_index_for_client_routes(client: TestClient) -> None:
    for path in ("/", "/library", "/system/status"):
        response = client.get(path)
        assert response.status_code == 200
        assert "<div id=root>" in response.text


def test_spa_serves_assets_and_404s_missing_ones(client: TestClient) -> None:
    assert client.get("/assets/app.js").text == "console.log('magarr')"
    assert client.get("/assets/missing.js").status_code == 404


def test_spa_blocks_path_traversal(client: TestClient) -> None:
    response = client.get("/..%2F..%2Fconfig%2Fconfig.yaml")
    assert "api_key" not in response.text


def test_frontend_not_built(settings: Settings, tmp_path) -> None:
    with TestClient(create_app(settings, frontend_dist=tmp_path / "missing")) as client:
        response = client.get("/")
    assert response.status_code == 503
    assert "npm run build" in response.text


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_basic_auth_protects_ui_and_accepts_api(settings: Settings, dist) -> None:
    settings.auth.basic_auth_enabled = True
    settings.auth.username = "admin"
    settings.auth.password = "s3cret"

    with TestClient(create_app(settings, frontend_dist=dist)) as client:
        denied = client.get("/")
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"].startswith("Basic")
        assert client.get("/initialize.json").status_code == 401
        assert client.get("/", headers=_basic("admin", "wrong")).status_code == 401
        assert client.get("/", headers=_basic("admin", "s3cret")).status_code == 200

        # API: basic creds or the API key both work.
        status = "/api/v1/system/status"
        assert client.get(status, headers=_basic("admin", "s3cret")).status_code == 200
        key = {"X-Api-Key": settings.auth.api_key}
        assert client.get(status, headers=key).json()["authentication"] == "basic"
        assert client.get("/health").status_code == 200


def test_malformed_basic_header_is_rejected(settings: Settings, dist) -> None:
    settings.auth.basic_auth_enabled = True
    settings.auth.username = "admin"
    settings.auth.password = "s3cret"
    with TestClient(create_app(settings, frontend_dist=dist)) as client:
        assert client.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401
