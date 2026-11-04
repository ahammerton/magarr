"""Phase 7 security pass: every API route needs the key; bodies and sizes are bounded."""

import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from magarr.core.auth import OPEN_PATHS


def _api_routes(client: TestClient) -> list[tuple[str, str]]:
    """Every HTTP route under /api, from the OpenAPI schema (it lists them all, with methods)."""
    routes = []
    for path, methods in client.app.openapi()["paths"].items():
        if path.startswith("/api/") and path not in OPEN_PATHS:
            concrete = re.sub(r"\{[^}]+\}", "1", path)
            routes.extend((method.upper(), concrete) for method in methods)
    return routes


def test_there_are_many_api_routes(client: TestClient) -> None:
    assert len(_api_routes(client)) > 80  # the audit below really covers the API


def test_every_api_route_needs_the_api_key(client: TestClient) -> None:
    open_routes = []
    for method, path in _api_routes(client):
        response = client.request(method, path, headers={"X-Api-Key": "wrong"})
        if response.status_code != 401:
            open_routes.append((method, path, response.status_code))
    assert open_routes == []


def test_the_queue_websocket_needs_the_api_key(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/ws/queue?apikey=wrong") as ws,
    ):
        ws.receive_json()


def test_request_bodies_are_capped(api: TestClient) -> None:
    huge = {"title": "x", "notes": "y" * (2 * 1024 * 1024)}
    response = api.post("/api/v1/magazine", json=huge)
    assert response.status_code == 413
    assert "larger than 1024 KB" in response.json()["message"]


def test_chunked_bodies_without_a_length_are_capped_too(api: TestClient) -> None:
    def chunks():
        for _ in range(40):
            yield b"x" * 65536  # 2.5 MiB, streamed

    response = api.post(
        "/api/v1/magazine", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_csv_import_may_be_larger(api: TestClient) -> None:
    row = f"Wired {'x' * 60},2024-01\n"
    csv = "magazine,issue\n" + row * 15_000  # ~1.1 MB, within the 20,000-row cap
    response = api.post("/api/v1/magazine/import", json={"csv": csv, "createMissing": False})
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/magazine", {"title": "x", "tags": ["t"] * 51}),
        ("/api/v1/magazine", {"title": "x", "alternateTitles": ["a" * 256]}),
        ("/api/v1/release/grab", {"guid": "g" * 3000, "indexerId": 1, "issueId": 1}),
        ("/api/v1/rootfolder", {"path": "/" + "a" * 1100}),
        ("/api/v1/qualityprofile", {"name": "p", "items": [], "mustContain": ["x"] * 101}),
    ],
)
def test_oversized_fields_are_rejected(api: TestClient, path: str, body: dict) -> None:
    assert api.post(path, json=body).status_code == 422


# --- Path traversal on import ------------------------------------------------------------------


@pytest.fixture
def issue(api: TestClient, magazine: dict) -> dict:
    return api.post(
        "/api/v1/issue",
        json={"magazineId": magazine["id"], "issueNumber": "2024-01", "publishDate": "2024-01-01"},
    ).json()


def _import(api: TestClient, path, issue: dict, **extra) -> dict:
    body = {"files": [{"path": str(path), "issueId": issue["id"]}], "mode": "copy", **extra}
    [outcome] = api.post("/api/v1/manualimport", json=body).json()
    return outcome


def test_manual_import_refuses_relative_paths_and_dot_dot(api, issue, tmp_path) -> None:
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "ng.pdf").write_bytes(b"pdf")
    assert "full path" in _import(api, "in/ng.pdf", issue)["error"]
    assert "full path" in _import(api, tmp_path / "in" / ".." / "in" / "ng.pdf", issue)["error"]


def test_manual_import_refuses_symlinks_and_non_magazine_files(api, issue, tmp_path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("password")
    link = tmp_path / "innocent.pdf"
    link.symlink_to(secret)
    assert "symbolic link" in _import(api, link, issue)["error"]
    assert "Not a magazine file" in _import(api, secret, issue)["error"]


def test_manual_import_for_a_download_stays_inside_it(api, issue, tmp_path) -> None:
    from magarr.domain.models import Download

    inside = tmp_path / "complete" / "NG"
    inside.mkdir(parents=True)
    (inside / "ng.pdf").write_bytes(b"pdf")
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"pdf")
    with api.app.state.session_factory() as session:
        download = Download(
            issue_id=issue["id"], external_id="x", title="NG", protocol="usenet",
            status="import_blocked", output_path=str(inside),
        )  # fmt: skip
        session.add(download)
        session.commit()
        download_id = download.id
    assert (
        "not part of this download" in _import(api, outside, issue, downloadId=download_id)["error"]
    )
    assert _import(api, inside / "ng.pdf", issue, downloadId=download_id)["error"] is None


def test_manual_import_wont_take_another_issues_file(api, magazine, issue, library_dir) -> None:
    taken = library_dir / magazine["folder"] / "NG 2024-02.pdf"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"pdf")
    api.post("/api/v1/library/scan", json={})
    assert "already the file of National Geographic 2024-02" in _import(api, taken, issue)["error"]


# --- SSRF --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[fe80::1]:8080/",
        "http://0.0.0.0:9696/",
        "http://224.0.0.1/",
        "http://metadata.internal/",  # a name that resolves to link-local
        "ftp://files.example/",
        "file:///etc/passwd",
    ],
)
def test_configured_urls_never_reach_metadata_or_odd_schemes(url: str, _no_real_dns) -> None:
    from magarr.core.netguard import UnsafeUrlError, check_configured_url

    _no_real_dns["metadata.internal"] = "169.254.169.254"
    with pytest.raises(UnsafeUrlError):
        check_configured_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:9696/",
        "http://127.0.0.1:8080/",
        "http://sabnzbd:8080/",
        "https://nzb.example/",
    ],
)
def test_configured_urls_may_be_on_the_lan(url: str) -> None:
    from magarr.core.netguard import check_configured_url

    check_configured_url(url)  # home servers: the LAN and container names are normal


def test_the_api_refuses_metadata_targets_everywhere(api: TestClient) -> None:
    meta = "169.254.169.254"
    responses = [
        api.post("/api/v1/indexer", json={"name": "x", "baseUrl": f"http://{meta}", "apiKey": "k"}),
        api.put("/api/v1/config/prowlarr", json={"url": f"http://{meta}:9696", "apiKey": "k"}),
        api.post(
            "/api/v1/downloadclient",
            json={
                "name": "x",
                "implementation": "sabnzbd",
                "settings": {"host": meta, "apiKey": "k"},
            },
        ),
        api.post(
            "/api/v1/notification",
            json={
                "name": "x",
                "implementation": "webhook",
                "settings": {"url": f"http://{meta}/hook"},
            },
        ),
    ]
    assert [r.status_code for r in responses] == [400] * 4
    assert all("won't connect" in r.json()["message"] for r in responses)


def _fetch(release_url: str, trusted: set, routes: dict) -> object:
    import asyncio

    import httpx
    import respx

    from magarr.domain.enums import IndexerImplementation
    from magarr.indexers.client import IndexerEndpoint, IndexerRelease
    from magarr.indexers.runtime import IndexerRuntime
    from magarr.pipeline.grab import fetch_payload

    endpoint = IndexerEndpoint(
        1, "Idx", IndexerImplementation.NEWZNAB, "https://nzb.example/", "/api", "k", ()
    )
    release = IndexerRelease(
        guid="g", title="NG", download_url=release_url, info_url=None, size=1, publish_date=None,
        categories=(), seeders=None, leechers=None, grabs=None, indexer_id=1, indexer="Idx",
        protocol=endpoint.protocol,
    )  # fmt: skip

    async def go():
        with respx.mock(assert_all_called=False) as mock:
            for url, response in routes.items():
                mock.get(url).mock(return_value=response)
            runtime = IndexerRuntime(httpx.AsyncClient())
            try:
                return await fetch_payload(runtime, release, trusted)
            finally:
                await runtime.aclose()

    return asyncio.run(go())


NZB = b'<?xml version="1.0"?><nzb xmlns="http://www.newzbin.com/DTD/2003/nzb"></nzb>'


def test_release_links_into_the_lan_are_refused(_no_real_dns) -> None:
    import ipaddress

    from magarr.core.netguard import UnsafeUrlError

    _no_real_dns.update(
        {
            "nzb.example": "93.184.216.34",
            "router.lan": "192.168.1.1",
            "prowlarr.lan": "192.168.1.10",
        }
    )
    httpx = pytest.importorskip("httpx")
    with pytest.raises(UnsafeUrlError, match="into your network"):
        _fetch("http://router.lan/cgi-bin/reboot", set(), {})
    with pytest.raises(UnsafeUrlError, match=r"169\.254\.169\.254"):
        _fetch("http://169.254.169.254/latest/", set(), {})

    # A public link that redirects into the LAN is caught at the redirect.
    redirect = httpx.Response(302, headers={"Location": "http://router.lan/admin"})
    with pytest.raises(UnsafeUrlError, match="into your network"):
        _fetch("https://nzb.example/getnzb/1", set(), {"https://nzb.example/getnzb/1": redirect})

    # The indexer's own LAN address is fine (Prowlarr serves its download links itself).
    trusted = {ipaddress.ip_address("192.168.1.10")}
    payload = _fetch(
        "http://prowlarr.lan/1/download?link=x",
        trusted,
        {"http://prowlarr.lan/1/download?link=x": httpx.Response(200, content=NZB)},
    )
    assert payload.content == NZB


# --- Headers -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/library", "/api/v1/system/status", "/initialize.json"])
def test_security_headers_everywhere(api: TestClient, path: str) -> None:
    headers = api.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    csp = headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp


def test_the_api_docs_page_may_load_swagger_from_its_cdn(client: TestClient) -> None:
    headers = client.get("/api/docs").headers
    assert "content-security-policy" not in headers
    assert headers["x-frame-options"] == "DENY"


def test_the_413_response_has_the_headers_too(api: TestClient) -> None:
    response = api.post("/api/v1/magazine", content=b"x" * (2 * 1024 * 1024))
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
