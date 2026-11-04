import json
from datetime import UTC, datetime, timedelta

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from magarr.domain.models import Indexer
from tests.indexer_fakes import NZB_URL, PROWLARR_URL, fixture, newznab_router, xml

NEW = {
    "name": "My NZB",
    "implementation": "newznab",
    "baseUrl": "https://nzb.example",
    "apiKey": "SECRET",
}


def _create(api: TestClient, **overrides) -> dict:
    response = api.post("/api/v1/indexer", json={**NEW, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_indexer_crud_and_key_masking(api: TestClient) -> None:
    created = _create(api, categories=[7010, 7000], tags=["Tech", "tech", ""])
    assert created["baseUrl"] == "https://nzb.example/"
    assert created["apiPath"] == "/api"
    assert created["apiKey"] == "********"
    assert created["protocol"] == "usenet"
    assert created["categories"] == [7000, 7010]
    assert created["tags"] == ["Tech"]
    assert created["priority"] == 25
    assert created["source"] == "manual"

    url = f"/api/v1/indexer/{created['id']}"
    # Echoing the mask back keeps the stored key.
    api.patch(url, json={"apiKey": "********", "priority": 5})
    session = api.app.state.session_factory()
    assert session.get(Indexer, created["id"]).api_key == "SECRET"
    session.close()

    updated = api.patch(url, json={"implementation": "torznab", "enabled": False}).json()
    assert (updated["protocol"], updated["enabled"], updated["priority"]) == ("torrent", False, 5)
    assert [i["id"] for i in api.get("/api/v1/indexer").json()] == [created["id"]]
    assert api.delete(url).status_code == 204
    assert api.get(url).status_code == 404


def test_indexer_validation(api: TestClient) -> None:
    _create(api)
    assert api.post("/api/v1/indexer", json={**NEW, "name": "my nzb"}).status_code == 409
    assert (
        api.post("/api/v1/indexer", json={**NEW, "name": "B", "baseUrl": "ftp://x"}).status_code
        == 400
    )
    assert api.post("/api/v1/indexer", json={**NEW, "name": "C", "priority": 0}).status_code == 400
    assert (
        api.post("/api/v1/indexer", json={**NEW, "name": "D", "categories": [-1]}).status_code
        == 400
    )
    assert (
        api.post("/api/v1/indexer", json={**NEW, "name": "E", "implementation": "x"}).status_code
        == 422
    )


@respx.mock
def test_test_unsaved_indexer(api: TestClient) -> None:
    respx.get(NZB_URL).mock(side_effect=newznab_router)
    result = api.post("/api/v1/indexer/test", json=NEW).json()
    assert result["ok"] is True
    assert {c["id"] for c in result["supportedCategories"]} == {7000, 7010, 7020, 7030}


@respx.mock
def test_test_reports_errors_without_raising(api: TestClient) -> None:
    respx.get(NZB_URL).mock(return_value=xml("newznab_error.xml"))
    result = api.post("/api/v1/indexer/test", json=NEW).json()
    assert result == {
        "ok": False,
        "message": "Indexer error 100: Incorrect user credentials",
        "supportedCategories": [],
    }
    assert api.post("/api/v1/indexer/test", json={**NEW, "baseUrl": "nope"}).json()["ok"] is False


@respx.mock
def test_test_saved_indexer_uses_stored_key_and_resets_health(api: TestClient) -> None:
    route = respx.get(NZB_URL).mock(side_effect=newznab_router)
    created = _create(api)
    session = api.app.state.session_factory()
    indexer = session.get(Indexer, created["id"])
    indexer.consecutive_failures = 5
    indexer.disabled_until = datetime.now(UTC) + timedelta(hours=1)
    session.commit()
    session.close()

    assert api.get(f"/api/v1/indexer/{created['id']}").json()["disabledUntil"] is not None
    result = api.post(f"/api/v1/indexer/{created['id']}/test").json()
    assert result["ok"] is True
    assert route.calls[0].request.url.params["apikey"] == "SECRET"
    after = api.get(f"/api/v1/indexer/{created['id']}").json()
    assert (after["disabledUntil"], after["consecutiveFailures"]) == (None, 0)
    assert {c["id"] for c in after["supportedCategories"]} == {7000, 7010, 7020, 7030}

    # Editing an existing indexer: test with the masked key uses the stored one.
    body = {**NEW, "id": created["id"], "apiKey": "********"}
    assert api.post("/api/v1/indexer/test", json=body).json()["ok"] is True
    assert route.calls[-1].request.url.params["apikey"] == "SECRET"


@respx.mock
def test_failed_test_records_failure(api: TestClient) -> None:
    respx.get(NZB_URL).mock(return_value=httpx.Response(500))
    created = _create(api)
    assert api.post(f"/api/v1/indexer/{created['id']}/test").json()["ok"] is False
    after = api.get(f"/api/v1/indexer/{created['id']}").json()
    assert after["consecutiveFailures"] == 1
    assert after["lastError"] == "Indexer returned HTTP 500"


def test_categories_endpoint(api: TestClient) -> None:
    ids = [c["id"] for c in api.get("/api/v1/indexer/categories").json()]
    assert 7010 in ids and 7000 in ids


# --- Prowlarr ---------------------------------------------------------------------------------


def _configure_prowlarr(api: TestClient) -> None:
    saved = api.put("/api/v1/config/prowlarr", json={"url": PROWLARR_URL, "apiKey": "PKEY"}).json()
    assert saved == {"url": f"{PROWLARR_URL}/", "apiKey": "********", "lastSync": None}


@respx.mock
def test_prowlarr_test_connection(api: TestClient) -> None:
    route = respx.get(f"{PROWLARR_URL}/api/v1/system/status").mock(
        return_value=httpx.Response(200, json={"version": "1.30.2.4939", "appName": "Prowlarr"})
    )
    result = api.post(
        "/api/v1/config/prowlarr/test", json={"url": PROWLARR_URL, "apiKey": "PKEY"}
    ).json()
    assert result["ok"] is True
    assert "1.30.2" in result["message"]
    assert route.calls[0].request.headers["X-Api-Key"] == "PKEY"

    _configure_prowlarr(api)
    api.post("/api/v1/config/prowlarr/test", json={"url": PROWLARR_URL, "apiKey": "********"})
    assert route.calls[-1].request.headers["X-Api-Key"] == "PKEY"

    respx.get(f"{PROWLARR_URL}/api/v1/system/status").mock(return_value=httpx.Response(401))
    bad = api.post("/api/v1/config/prowlarr/test", json={"url": PROWLARR_URL, "apiKey": "x"}).json()
    assert bad == {
        "ok": False,
        "message": "Prowlarr rejected the API key",
        "supportedCategories": [],
    }


def test_sync_requires_config(api: TestClient) -> None:
    response = api.post("/api/v1/indexer/sync-prowlarr")
    assert response.status_code == 400
    assert "Prowlarr URL" in response.json()["message"]


@respx.mock
def test_prowlarr_sync(api: TestClient) -> None:
    _configure_prowlarr(api)
    payload = json.loads(fixture("prowlarr_indexers.json"))
    route = respx.get(f"{PROWLARR_URL}/api/v1/indexer").mock(
        return_value=httpx.Response(200, json=payload)
    )
    manual = _create(api, name="NZBGeek (Prowlarr)")  # name clash with a synced one

    result = api.post("/api/v1/indexer/sync-prowlarr").json()
    assert route.calls[0].request.headers["X-Api-Key"] == "PKEY"
    assert result["added"] == ["NZBGeek (Prowlarr) 2", "Public Tracker (Prowlarr)"]
    assert result["updated"] == [] and result["removed"] == []
    assert result["skipped"] == [
        {"name": "Movies Only", "reason": "No book or magazine categories"},
        {"name": "Switched Off", "reason": "Disabled in Prowlarr"},
    ]

    indexers = {i["name"]: i for i in api.get("/api/v1/indexer").json()}
    geek = indexers["NZBGeek (Prowlarr) 2"]
    assert geek["baseUrl"] == f"{PROWLARR_URL}/1/"
    assert geek["apiPath"] == "/api"
    assert (geek["implementation"], geek["priority"], geek["categories"]) == ("newznab", 10, [7010])
    assert (geek["source"], geek["prowlarrId"]) == ("prowlarr", 1)
    tracker = indexers["Public Tracker (Prowlarr)"]
    assert (tracker["implementation"], tracker["categories"]) == ("torznab", [7000])
    assert api.get("/api/v1/config/prowlarr").json()["lastSync"] is not None

    # User edits to categories/tags/enabled survive a re-sync; removed indexers go away.
    api.patch(
        f"/api/v1/indexer/{geek['id']}",
        json={"categories": [7010, 7020], "tags": ["x"], "enabled": False},
    )
    payload[0]["priority"] = 3
    del payload[1]
    respx.get(f"{PROWLARR_URL}/api/v1/indexer").mock(return_value=httpx.Response(200, json=payload))
    again = api.post("/api/v1/indexer/sync-prowlarr").json()
    assert again["updated"] == ["NZBGeek (Prowlarr) 2"]
    assert again["removed"] == ["Public Tracker (Prowlarr)"]
    geek = api.get(f"/api/v1/indexer/{geek['id']}").json()
    assert (geek["priority"], geek["categories"], geek["tags"], geek["enabled"]) == (
        3,
        [7010, 7020],
        ["x"],
        False,
    )
    # Manual indexers are never touched by sync.
    assert api.get(f"/api/v1/indexer/{manual['id']}").status_code == 200

    session = api.app.state.session_factory()
    assert session.scalar(select(Indexer.api_key).where(Indexer.prowlarr_id == 1)) == "PKEY"
    session.close()


@respx.mock
def test_prowlarr_sync_bad_response(api: TestClient) -> None:
    _configure_prowlarr(api)
    respx.get(f"{PROWLARR_URL}/api/v1/indexer").mock(
        return_value=httpx.Response(200, text="<html>")
    )
    response = api.post("/api/v1/indexer/sync-prowlarr")
    assert response.status_code == 400
    assert "did not return JSON" in response.json()["message"]
