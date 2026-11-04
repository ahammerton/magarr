import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.domain.models import Download
from magarr.pipeline.tracking import MISSING_POLLS_BEFORE_WARNING, poll_once
from tests.download_fakes import SAB_KEY, SAB_URL, FakeSab
from tests.indexer_fakes import NZB_URL, fixture, newznab_router


@pytest.fixture
def sab() -> FakeSab:
    return FakeSab()


@pytest.fixture
def setup(api: TestClient, magazine: dict, sab: FakeSab):
    """Indexer + SABnzbd + a wanted issue matching the Newznab fixture (January 2025)."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(NZB_URL).mock(side_effect=newznab_router)
        mock.get(url__startswith="https://nzb.example/getnzb/").mock(
            return_value=httpx.Response(200, content=fixture("sample.nzb"))
        )
        mock.route(url__startswith=SAB_URL).mock(side_effect=sab)
        api.post(
            "/api/v1/indexer",
            json={
                "name": "Usenet",
                "baseUrl": "https://nzb.example",
                "apiKey": "K",
                "requestInterval": 0,
            },
        )
        client = api.post(
            "/api/v1/downloadclient",
            json={
                "name": "SAB",
                "implementation": "sabnzbd",
                "settings": {"host": "sab.local", "apiKey": SAB_KEY, "category": "magazines"},
            },
        )
        assert client.status_code == 201, client.text
        issue = api.post(
            "/api/v1/issue",
            json={
                "magazineId": magazine["id"],
                "issueNumber": "2025-01",
                "publishDate": "2025-01-01",
                "monitored": True,
            },
        ).json()
        yield {"issue": issue, "mock": mock}


def _search(api: TestClient, issue: dict) -> list[dict]:
    return api.post(f"/api/v1/issue/{issue['id']}/search").json()["releases"]


def _poll(api: TestClient):
    """Poll on the app's own event loop: its shared HTTP client belongs to that loop."""

    async def go():
        with api.app.state.session_factory() as session:
            return await poll_once(session, api.app.state.indexer_runtime)

    return api.portal.call(go)


def _issue(api: TestClient, issue: dict) -> dict:
    issues = api.get(f"/api/v1/issue?magazineId={issue['magazineId']}").json()
    return next(i for i in issues if i["id"] == issue["id"])


def test_grab_sends_nzb_and_tracks_to_pending_import(api: TestClient, setup, sab: FakeSab) -> None:
    issue = setup["issue"]
    releases = _search(api, issue)
    best = next(r for r in releases if not r["rejected"])
    assert (
        best["title"] == "National.Geographic.USA.2025.01.HYBRID.MAGAZiNE.eBook-PDF"
    )  # newest PDF

    grabbed = api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    assert grabbed.status_code == 201, grabbed.text
    download = grabbed.json()
    assert (download["status"], download["title"], download["protocol"]) == (
        "queued",
        best["title"],
        "usenet",
    )
    assert sab.added[0]["cat"] == "magazines"
    assert sab.added[0]["file"].endswith(".nzb")
    nzo = sab.added[0]["nzo_id"]

    # The issue now shows its download; history has the grab with a key-free release snapshot.
    assert _issue(api, issue)["download"]["status"] == "queued"
    history = api.get(f"/api/v1/history?issueId={issue['id']}").json()
    assert [r["eventType"] for r in history["records"]] == ["grabbed"]
    snapshot = history["records"][0]["data"]["release"]
    assert "download_url" not in snapshot and "r=KEY" not in str(history)
    assert history["records"][0]["data"]["source"] == "manual grab"

    sab.progress(nzo, left_mb=10)
    summary = _poll(api)
    assert summary.checked == 1
    current = _issue(api, issue)["download"]
    assert (current["status"], current["progress"]) == ("downloading", 0.75)

    sab.complete(nzo, "/downloads/magazines/National.Geographic.USA.2025.01")
    summary = _poll(api)
    assert summary.completed == [download["id"]]
    queue = api.get("/api/v1/queue").json()
    assert [(q["status"], q["outputPath"]) for q in queue] == [
        ("pending_import", "/downloads/magazines/National.Geographic.USA.2025.01")
    ]
    events = [
        r["eventType"] for r in api.get(f"/api/v1/history?issueId={issue['id']}").json()["records"]
    ]
    assert events == ["download_completed", "grabbed"]
    assert _issue(api, issue)["download"]["status"] == "pending_import"
    # Further polls leave a pending import alone.
    assert _poll(api).checked == 0


def test_failed_download_blocklists_and_grabs_next_best(
    api: TestClient, setup, sab: FakeSab
) -> None:
    issue = setup["issue"]
    best = next(r for r in _search(api, issue) if not r["rejected"])
    api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    first = sab.added[0]["nzo_id"]

    sab.fail(first, "Out of retention")
    api.app.state.indexer_runtime.cache.clear()  # the retry search must hit the indexer again
    summary = _poll(api)
    assert summary.failed and summary.retried == [issue["id"]]

    # The failed release is blocklisted and rejected; the next-best one was grabbed.
    assert len(sab.added) == 2
    blocklist = api.get("/api/v1/blocklist").json()
    assert [(b["sourceTitle"], b["reason"]) for b in blocklist] == [
        (best["title"], "Out of retention")
    ]
    events = [
        r["eventType"] for r in api.get(f"/api/v1/history?issueId={issue['id']}").json()["records"]
    ]
    assert events == ["grabbed", "download_failed", "grabbed"]
    retry = api.get(f"/api/v1/history?issueId={issue['id']}").json()["records"][0]
    assert retry["data"]["source"] == "automatic retry after failure"
    assert retry["sourceTitle"] == "National.Geographic.UK.2025.01.True.PDF"

    results = {r["title"]: r for r in _search(api, issue)}
    # While the retry downloads, the failed release is both blocklisted and redundant.
    assert results[best["title"]]["rejectionReasons"] == [
        "Blocklisted after an earlier failed download",
        "This issue already has a download in progress",
    ]


def test_failure_without_redownload(api: TestClient, setup, sab: FakeSab) -> None:
    api.put("/api/v1/config/downloads", json={"redownloadFailed": False})
    issue = setup["issue"]
    best = next(r for r in _search(api, issue) if not r["rejected"])
    api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    sab.fail(sab.added[0]["nzo_id"], "CRC error")
    summary = _poll(api)
    assert summary.retried == [] and len(sab.added) == 1
    assert _issue(api, issue)["download"] is None  # failed downloads are not "current"
    assert _issue(api, issue)["status"] == "wanted"


def test_missing_item_becomes_warning_not_failure(api: TestClient, setup, sab: FakeSab) -> None:
    issue = setup["issue"]
    best = next(r for r in _search(api, issue) if not r["rejected"])
    api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    sab.forget(sab.added[0]["nzo_id"])
    for _ in range(MISSING_POLLS_BEFORE_WARNING):
        _poll(api)
    current = _issue(api, issue)["download"]
    assert (current["status"], current["message"]) == ("warning", "No longer found in SAB")
    assert api.get("/api/v1/blocklist").json() == []


def test_active_download_rejects_other_releases(api: TestClient, setup) -> None:
    issue = setup["issue"]
    best = next(r for r in _search(api, issue) if not r["rejected"])
    api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    after = _search(api, issue)
    assert not any(not r["rejected"] for r in after)
    assert all(
        "This issue already has a download in progress" in r["rejectionReasons"]
        for r in after
        if r["parsed"]["issueNumber"] == "2025-01"
    )


def test_grab_errors(api: TestClient, setup) -> None:
    issue = setup["issue"]
    stale = api.post(
        "/api/v1/release/grab", json={"guid": "nope", "indexerId": 1, "issueId": issue["id"]}
    )
    assert stale.status_code == 400
    assert "search again" in stale.json()["message"]

    best = next(r for r in _search(api, issue) if not r["rejected"])
    setup["mock"].get(url__startswith="https://nzb.example/getnzb/").mock(
        return_value=httpx.Response(
            200, content=b"<error code='429' description='Request limit reached'/>"
        )
    )
    response = api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    assert response.status_code == 502
    assert "did not return an NZB" in response.json()["message"]
    assert api.get("/api/v1/queue").json() == []


def test_grab_without_matching_client(api: TestClient, setup) -> None:
    issue = setup["issue"]
    [client] = api.get("/api/v1/downloadclient").json()
    api.patch(f"/api/v1/downloadclient/{client['id']}", json={"enabled": False})
    best = next(r for r in _search(api, issue) if not r["rejected"])
    response = api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    assert response.status_code == 400
    assert response.json()["message"] == "No enabled download client for usenet releases"


def test_unblocking(api: TestClient, setup, sab: FakeSab) -> None:
    api.put("/api/v1/config/downloads", json={"redownloadFailed": False})
    issue = setup["issue"]
    best = next(r for r in _search(api, issue) if not r["rejected"])
    api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    sab.fail(sab.added[0]["nzo_id"], "x")
    _poll(api)
    [item] = api.get("/api/v1/blocklist").json()
    assert api.delete(f"/api/v1/blocklist/{item['id']}").status_code == 204
    results = {r["title"]: r for r in _search(api, issue)}
    assert not results[best["title"]]["rejected"]


def test_poller_runs_in_background(settings, dist, sab: FakeSab) -> None:
    """The app starts the poller; a short interval should poll without anyone calling it."""
    from magarr.main import create_app

    settings.downloads.poll_interval = 0.5
    with (
        respx.mock(assert_all_called=False) as mock,
        TestClient(create_app(settings, frontend_dist=dist)) as client,
    ):
        mock.route(url__startswith=SAB_URL).mock(side_effect=sab)
        client.headers["X-Api-Key"] = settings.auth.api_key
        root = client.app.state
        with root.session_factory() as session:
            from magarr.domain.models import DownloadClient as Row

            row = Row(
                name="SAB",
                implementation="sabnzbd",
                settings={"host": "sab.local", "port": 8080, "api_key": SAB_KEY},
            )
            session.add(row)
            session.flush()
            session.add(
                Download(
                    download_client_id=row.id,
                    external_id="SABnzbd_nzo_bg",
                    title="BG",
                    protocol="usenet",
                    release={},
                )
            )
            session.commit()
        sab.queue["SABnzbd_nzo_bg"] = {
            "nzo_id": "SABnzbd_nzo_bg",
            "filename": "BG",
            "status": "Downloading",
            "mb": "10",
            "mbleft": "5",
        }
        import time

        for _ in range(40):
            time.sleep(0.1)
            if client.get("/api/v1/queue").json()[0]["progress"] == 0.5:
                break
        assert client.get("/api/v1/queue").json()[0]["status"] == "downloading"
