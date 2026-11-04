import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from magarr.domain.models import DownloadClient
from tests.download_fakes import SAB_KEY, SAB_URL, FakeSab

SAB = {
    "name": "SAB",
    "implementation": "sabnzbd",
    "settings": {"host": "sab.local", "apiKey": SAB_KEY},
}


def test_schema_lists_fields_per_implementation(api: TestClient) -> None:
    schema = {s["implementation"]: s for s in api.get("/api/v1/downloadclient/schema").json()}
    assert set(schema) == {"sabnzbd", "nzbget", "qbittorrent", "deluge", "transmission", "rtorrent"}
    assert (schema["sabnzbd"]["protocol"], schema["qbittorrent"]["protocol"]) == (
        "usenet",
        "torrent",
    )
    sab = {f["name"]: f for f in schema["sabnzbd"]["fields"]}
    assert sab["apiKey"]["type"] == "password" and sab["apiKey"]["required"]
    assert (sab["port"]["type"], sab["port"]["default"]) == ("number", 8080)
    assert sab["useSsl"]["type"] == "boolean"
    assert sab["priority"]["type"] == "select" and "high" in sab["priority"]["options"]
    qb = {f["name"]: f for f in schema["qbittorrent"]["fields"]}
    assert qb["password"]["type"] == "password" and qb["username"]["default"] == "admin"


def test_crud_masks_and_keeps_secrets(api: TestClient) -> None:
    created = api.post("/api/v1/downloadclient", json=SAB)
    assert created.status_code == 201, created.text
    client = created.json()
    assert client["protocol"] == "usenet"
    assert client["settings"]["apiKey"] == "********"
    assert client["settings"]["port"] == 8080 and client["settings"]["category"] == "magazines"

    settings = {**client["settings"], "category": "books"}  # apiKey still masked
    updated = api.patch(
        f"/api/v1/downloadclient/{client['id']}", json={"settings": settings, "priority": 3}
    )
    assert updated.status_code == 200, updated.text
    with api.app.state.session_factory() as session:
        row = session.scalar(select(DownloadClient))
        assert row.settings["api_key"] == SAB_KEY
        assert row.settings["category"] == "books"
    assert updated.json()["priority"] == 3

    assert api.delete(f"/api/v1/downloadclient/{client['id']}").status_code == 204
    assert api.get("/api/v1/downloadclient").json() == []


def test_validation(api: TestClient) -> None:
    bad = api.post("/api/v1/downloadclient", json={**SAB, "settings": {"host": "sab.local"}})
    assert bad.json() == {"message": "apiKey: Field required"}
    unknown = api.post(
        "/api/v1/downloadclient", json={**SAB, "settings": {**SAB["settings"], "bogus": 1}}
    )
    assert unknown.status_code == 400
    assert api.post("/api/v1/downloadclient", json={**SAB, "priority": 0}).status_code == 400
    api.post("/api/v1/downloadclient", json=SAB)
    assert api.post("/api/v1/downloadclient", json={**SAB, "name": "sab"}).status_code == 409


@respx.mock
def test_test_endpoints(api: TestClient) -> None:
    respx.route(url__startswith=SAB_URL).mock(side_effect=FakeSab())
    ok = api.post(
        "/api/v1/downloadclient/test",
        json={"implementation": "sabnzbd", "settings": SAB["settings"]},
    ).json()
    assert ok == {"ok": True, "message": "Connected to SABnzbd 5.1.3", "warnings": []}
    warn = api.post(
        "/api/v1/downloadclient/test",
        json={"implementation": "sabnzbd", "settings": {**SAB["settings"], "category": "mags"}},
    ).json()
    assert warn["ok"] and "Category 'mags' does not exist" in warn["warnings"][0]
    bad = api.post(
        "/api/v1/downloadclient/test",
        json={"implementation": "sabnzbd", "settings": {**SAB["settings"], "apiKey": "x"}},
    ).json()
    assert bad == {"ok": False, "message": "SABnzbd: API Key Incorrect", "warnings": []}

    saved = api.post("/api/v1/downloadclient", json=SAB).json()
    assert api.post(f"/api/v1/downloadclient/{saved['id']}/test").json()["ok"]
    # Editing a saved client: masked key resolves to the stored one.
    masked = api.post(
        "/api/v1/downloadclient/test",
        json={"implementation": "sabnzbd", "settings": saved["settings"], "id": saved["id"]},
    ).json()
    assert masked["ok"], masked


def test_download_settings(api: TestClient) -> None:
    assert api.get("/api/v1/config/downloads").json() == {"redownloadFailed": True, "maxRetries": 3}
    saved = api.put("/api/v1/config/downloads", json={"redownloadFailed": False, "maxRetries": 1})
    assert saved.json() == {"redownloadFailed": False, "maxRetries": 1}
    assert api.get("/api/v1/config/downloads").json()["maxRetries"] == 1
    bad = api.put("/api/v1/config/downloads", json={"redownloadFailed": True, "maxRetries": -1})
    assert bad.status_code == 422


def test_profile_rules_round_trip_and_validation(api: TestClient) -> None:
    [profile] = api.get("/api/v1/qualityprofile").json()
    assert (profile["protocols"], profile["mustContain"], profile["mustNotContain"]) == (
        ["usenet", "torrent"],
        [],
        [],
    )
    body = {
        **profile,
        "protocols": ["torrent", "usenet", "usenet"][:1],
        "mustContain": [" True PDF ", ""],
        "mustNotContain": ["/spanish|italian/"],
    }
    saved = api.put(f"/api/v1/qualityprofile/{profile['id']}", json=body).json()
    assert (saved["protocols"], saved["mustContain"], saved["mustNotContain"]) == (
        ["torrent"],
        ["True PDF"],
        ["/spanish|italian/"],
    )
    assert (
        api.put(
            f"/api/v1/qualityprofile/{profile['id']}", json={**body, "protocols": []}
        ).status_code
        == 400
    )
    assert (
        api.put(
            f"/api/v1/qualityprofile/{profile['id']}", json={**body, "protocols": ["ftp"]}
        ).status_code
        == 400
    )
    bad = api.put(f"/api/v1/qualityprofile/{profile['id']}", json={**body, "mustContain": ["/(x/"]})
    assert bad.status_code == 400 and "Invalid regular expression" in bad.json()["message"]
