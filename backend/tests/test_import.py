"""Phase 4: completed downloads are imported into the library (fake SABnzbd, real files)."""

import errno
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.domain.models import Download
from magarr.pipeline.tracking import poll_once
from tests.download_fakes import SAB_KEY, SAB_URL, FakeSab
from tests.indexer_fakes import NZB_URL, fixture, newznab_router

REMOTE = "/data/usenet/complete"


@pytest.fixture
def sab() -> FakeSab:
    return FakeSab()


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    """Where Magarr sees SABnzbd's /data/usenet/complete."""
    path = tmp_path / "nas" / "usenet" / "complete"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def env(api: TestClient, magazine: dict, sab: FakeSab, downloads: Path, library_dir: Path):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(NZB_URL).mock(side_effect=newznab_router)
        mock.get(url__startswith="https://nzb.example/getnzb/").mock(
            return_value=httpx.Response(200, content=fixture("sample.nzb"))
        )
        sab_route = mock.route(url__startswith=SAB_URL).mock(side_effect=sab)
        api.post(
            "/api/v1/indexer",
            json={
                "name": "Usenet",
                "baseUrl": "https://nzb.example",
                "apiKey": "K",
                "requestInterval": 0,
            },
        )
        api.post(
            "/api/v1/downloadclient",
            json={
                "name": "SAB",
                "implementation": "sabnzbd",
                "settings": {"host": "sab.local", "apiKey": SAB_KEY},
            },
        )
        api.post(
            "/api/v1/remotepathmapping",
            json={
                "host": "sab.local",
                "remotePath": "/data",
                "localPath": str(downloads.parent.parent),
            },
        )
        issues = {}
        for number in ("2025-01", "2025-02", "2025-03"):
            issues[number] = api.post(
                "/api/v1/issue",
                json={
                    "magazineId": magazine["id"],
                    "issueNumber": number,
                    "publishDate": f"{number}-01",
                    "monitored": True,
                },
            ).json()
        yield {"issues": issues, "magazine": magazine, "sab_route": sab_route, "mock": mock}


def _poll(api: TestClient):
    async def go():
        with api.app.state.session_factory() as session:
            return await poll_once(session, api.app.state.indexer_runtime)

    return api.portal.call(go)


def _grab(api: TestClient, issue: dict) -> dict:
    releases = api.post(f"/api/v1/issue/{issue['id']}/search").json()["releases"]
    best = next(r for r in releases if not r["rejected"])
    response = api.post(
        "/api/v1/release/grab",
        json={"guid": best["guid"], "indexerId": best["indexerId"], "issueId": issue["id"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _complete(
    sab: FakeSab, downloads: Path, files: dict[str, bytes], folder: str = "NG.Release"
) -> Path:
    nzo = sab.added[-1]["nzo_id"]
    target = downloads / folder
    for name, data in files.items():
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(data)
    sab.complete(nzo, f"{REMOTE}/{folder}")
    return target


def _issue(api: TestClient, issue: dict) -> dict:
    return api.get(f"/api/v1/issue/{issue['id']}").json()


def test_completed_download_is_imported_renamed_and_cleaned_up(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path
) -> None:
    """The Phase 4 definition of done (default naming: no year folders)."""
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    source = _complete(
        sab, downloads, {"ng.pdf": b"%PDF magazine", "file_id.diz": b"x", "info.nfo": b"y"}
    )

    summary = _poll(api)
    assert summary.imported, summary

    expected = (
        library_dir
        / "National Geographic (1888)"
        / "National Geographic - 2025-01 - Issue 2025-01.pdf"
    )
    assert expected.read_bytes() == b"%PDF magazine"
    assert not source.exists()  # moved, and the junk-only folder removed
    imported = _issue(api, issue)
    assert imported["status"] == "downloaded"
    assert imported["file"]["relativePath"] == "National Geographic - 2025-01 - Issue 2025-01.pdf"
    assert imported["file"]["quality"] == "pdf"
    assert imported["download"] is None  # no longer in the queue
    assert api.get("/api/v1/queue").json() == []
    events = [
        e["eventType"] for e in api.get(f"/api/v1/history?issueId={issue['id']}").json()["records"]
    ]
    assert events == ["imported", "download_completed", "grabbed"]
    # SABnzbd is told to forget the finished item.
    deletes = [
        c.request.url.params
        for c in env["sab_route"].calls
        if c.request.url.params.get("name") == "delete"
    ]
    assert {d["mode"] for d in deletes} == {"queue", "history"} and all(
        d["del_files"] == "0" for d in deletes
    )


def test_unseen_path_waits_for_a_mapping(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path
) -> None:
    [mapping] = api.get("/api/v1/remotepathmapping").json()
    api.delete(f"/api/v1/remotepathmapping/{mapping['id']}")
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _poll(api)
    [queued] = api.get("/api/v1/queue").json()
    assert queued["status"] == "pending_import"
    assert (
        "Add a remote path mapping" in queued["message"]
        and f"{REMOTE}/NG.Release" in queued["message"]
    )

    api.post(
        "/api/v1/remotepathmapping",
        json={"host": "sab.local", "remotePath": REMOTE, "localPath": str(downloads)},
    )
    _poll(api)  # retried automatically
    assert _issue(api, issue)["status"] == "downloaded"


def test_obfuscated_single_file_goes_to_grabbed_issue(
    api: TestClient, env, sab: FakeSab, downloads: Path
) -> None:
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    _complete(sab, downloads, {"a8f3k2Lq.pdf": b"pdf"})
    _poll(api)
    assert _issue(api, issue)["file"]["relativePath"].endswith("Issue 2025-01.pdf")


def test_files_named_for_other_issues_go_there(
    api: TestClient, env, sab: FakeSab, downloads: Path
) -> None:
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    _complete(sab, downloads, {"National Geographic 2025-03.pdf": b"pdf", "cover.pdf": b"img"})
    _poll(api)
    # The named file goes to the issue it says it is (2025-03); the one unnamed file fills the
    # grabbed issue, since the release itself said which issue that is.
    assert _issue(api, env["issues"]["2025-03"])["status"] == "downloaded"
    assert _issue(api, issue)["status"] == "downloaded"


def test_pack_fills_several_issues(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path
) -> None:
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    _complete(sab, downloads, {
        "NG 2025-01.pdf": b"jan", "NG 2025-02.pdf": b"feb", "NG 2025-03.epub": b"mar", "NG 2025-04.pdf": b"apr",
    })  # fmt: skip
    _poll(api)
    statuses = {n: _issue(api, i)["status"] for n, i in env["issues"].items()}
    assert statuses == {"2025-01": "downloaded", "2025-02": "downloaded", "2025-03": "downloaded"}
    assert _issue(api, env["issues"]["2025-03"])["file"]["format"] == "epub"
    [download] = [d for d in api.get("/api/v1/queue").json()] or [None]
    assert download is None  # imported, even though one file (2025-04, no such issue) was skipped
    with api.app.state.session_factory() as session:
        row = session.query(Download).one()
        assert row.status == "imported"
        assert "1 file(s) not imported" in row.message
    assert (downloads / "NG.Release" / "NG 2025-04.pdf").exists()  # left for manual import


def test_best_format_wins_within_a_download(
    api: TestClient, env, sab: FakeSab, downloads: Path
) -> None:
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    _complete(sab, downloads, {"NG 2025-01.epub": b"e", "NG 2025-01.pdf": b"p"})
    _poll(api)
    assert _issue(api, issue)["file"]["format"] == "pdf"  # PDF ranks above EPUB in "Any"


def test_upgrade_replaces_into_recycle_bin(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path, tmp_path: Path
) -> None:
    settings = api.get("/api/v1/config/mediamanagement").json()
    api.put(
        "/api/v1/config/mediamanagement", json={**settings, "recycleBin": str(tmp_path / "bin")}
    )
    issue = env["issues"]["2025-01"]
    folder = library_dir / "National Geographic (1888)"
    old = folder / "NG 2025-01.epub"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old epub")
    api.post("/api/v1/library/scan", json={})
    assert _issue(api, issue)["file"]["format"] == "epub"

    api.app.state.indexer_runtime.cache.clear()
    _grab(api, issue)
    _complete(sab, downloads, {"ng.pdf": b"new pdf"})
    _poll(api)
    upgraded = _issue(api, issue)
    assert (upgraded["file"]["format"], upgraded["file"]["quality"]) == ("pdf", "pdf")
    assert not old.exists()
    assert (
        tmp_path / "bin" / "National Geographic (1888)" / "NG 2025-01.epub"
    ).read_bytes() == b"old epub"
    events = [
        e["eventType"] for e in api.get(f"/api/v1/history?issueId={issue['id']}").json()["records"]
    ]
    assert events[:2] == ["upgraded", "file_deleted"]


def test_not_an_upgrade_is_blocked(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path
) -> None:
    issue = env["issues"]["2025-01"]
    existing = library_dir / "National Geographic (1888)" / "NG 2025-01.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"have")
    api.post("/api/v1/library/scan", json={})
    with api.app.state.session_factory() as session:
        from magarr.domain.models import Issue as IssueRow

        row = session.get(IssueRow, issue["id"])
        # A PDF (Hi-Res) file already: the decision engine would reject, so force a manual grab path.
        row.file.quality = "pdf_hires"
        session.commit()
    releases = api.post(f"/api/v1/issue/{issue['id']}/search").json()["releases"]
    candidate = next(r for r in releases if r["parsed"]["issueNumber"] == "2025-01")
    api.post(
        "/api/v1/release/grab",
        json={
            "guid": candidate["guid"],
            "indexerId": candidate["indexerId"],
            "issueId": issue["id"],
        },
    )
    _complete(sab, downloads, {"ng.pdf": b"worse"})
    _poll(api)
    [queued] = api.get("/api/v1/queue").json()
    assert queued["status"] == "import_blocked"
    assert queued["message"] == "Not an upgrade: the issue already has a PDF (Hi-Res) file"
    assert existing.read_bytes() == b"have"


def test_no_media_files_is_blocked(api: TestClient, env, sab: FakeSab, downloads: Path) -> None:
    _grab(api, env["issues"]["2025-01"])
    _complete(sab, downloads, {"readme.txt": b"x", "sample.pdf": b"s"})
    _poll(api)
    [queued] = api.get("/api/v1/queue").json()
    assert (queued["status"], queued["message"]) == (
        "import_blocked",
        f"No magazine files found in {downloads / 'NG.Release'}",
    )


def test_auto_import_off_waits_then_retry_endpoint(
    api: TestClient, env, sab: FakeSab, downloads: Path
) -> None:
    settings = api.get("/api/v1/config/mediamanagement").json()
    api.put("/api/v1/config/mediamanagement", json={**settings, "autoImport": False})
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _poll(api)
    [queued] = api.get("/api/v1/queue").json()
    assert queued["status"] == "pending_import"
    retried = api.post(f"/api/v1/queue/{queued['id']}/import").json()
    assert retried["status"] == "imported"
    assert _issue(api, issue)["status"] == "downloaded"


def test_copy_mode_keeps_source(api: TestClient, env, sab: FakeSab, downloads: Path) -> None:
    settings = api.get("/api/v1/config/mediamanagement").json()
    api.put("/api/v1/config/mediamanagement", json={**settings, "usenetImportMode": "copy"})
    _grab(api, env["issues"]["2025-01"])
    source = _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _poll(api)
    assert (source / "ng.pdf").exists()
    assert not any(c.request.url.params.get("name") == "delete" for c in env["sab_route"].calls)


# --- manual import, queue actions, websocket --------------------------------------------------


def test_manual_import_from_folder(api: TestClient, env, tmp_path: Path, library_dir: Path) -> None:
    inbox = tmp_path / "inbox" / "National Geographic"
    inbox.mkdir(parents=True)
    (inbox / "National Geographic 2025-02.pdf").write_bytes(b"feb")
    (inbox / "random.pdf").write_bytes(b"?")
    (inbox / "notes.txt").write_bytes(b"ignored")

    scan = api.get("/api/v1/manualimport", params={"path": str(tmp_path / "inbox")}).json()
    items = {i["relativePath"]: i for i in scan["items"]}
    assert set(items) == {
        "National Geographic/National Geographic 2025-02.pdf",
        "National Geographic/random.pdf",
    }
    feb = items["National Geographic/National Geographic 2025-02.pdf"]
    assert (feb["magazineId"], feb["issueId"], feb["warnings"]) == (
        env["magazine"]["id"],
        env["issues"]["2025-02"]["id"],
        [],
    )
    rand = items["National Geographic/random.pdf"]
    assert rand["magazineId"] == env["magazine"]["id"]  # from the folder name
    assert rand["issueId"] is None and rand["warnings"] == ["Choose the issue"]

    result = api.post("/api/v1/manualimport", json={"mode": "copy", "files": [
        {"path": feb["path"], "issueId": feb["issueId"]},
        {"path": rand["path"], "issueId": env["issues"]["2025-03"]["id"], "quality": "pdf_hires"},
        {"path": str(inbox / "notes.txt"), "issueId": env["issues"]["2025-01"]["id"]},
    ]}).json()  # fmt: skip
    assert [r["error"] for r in result] == [
        None,
        None,
        f"Not a magazine file: {inbox / 'notes.txt'}",
    ]
    assert _issue(api, env["issues"]["2025-03"])["file"]["quality"] == "pdf_hires"
    assert (inbox / "random.pdf").exists()  # copy mode


def test_manual_import_for_blocked_download(
    api: TestClient, env, sab: FakeSab, downloads: Path
) -> None:
    _grab(api, env["issues"]["2025-01"])
    _complete(sab, downloads, {"x1.pdf": b"a", "x2.pdf": b"b"})  # two unrecognizable files
    _poll(api)
    [queued] = api.get("/api/v1/queue").json()
    assert queued["status"] == "import_blocked"
    scan = api.get("/api/v1/manualimport", params={"downloadId": queued["id"]}).json()
    assert len(scan["items"]) == 2
    first = scan["items"][0]
    api.post(
        "/api/v1/manualimport",
        json={
            "downloadId": queued["id"],
            "files": [{"path": first["path"], "issueId": env["issues"]["2025-01"]["id"]}],
        },
    )
    assert api.get("/api/v1/queue").json() == []
    assert _issue(api, env["issues"]["2025-01"])["status"] == "downloaded"


def test_remove_from_queue_with_blocklist(api: TestClient, env, sab: FakeSab) -> None:
    download = _grab(api, env["issues"]["2025-01"])
    assert api.delete(f"/api/v1/queue/{download['id']}?blocklist=true").status_code == 204
    assert api.get("/api/v1/queue").json() == []
    assert [b["sourceTitle"] for b in api.get("/api/v1/blocklist").json()] == [download["title"]]
    deletes = [
        c.request.url.params
        for c in env["sab_route"].calls
        if c.request.url.params.get("name") == "delete"
    ]
    assert deletes and all(d["del_files"] == "1" for d in deletes)


def test_history_filters(api: TestClient, env, sab: FakeSab, downloads: Path) -> None:
    _grab(api, env["issues"]["2025-01"])
    _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _poll(api)
    page = api.get(
        "/api/v1/history", params={"eventType": "imported", "magazineId": env["magazine"]["id"]}
    ).json()
    assert page["total"] == 1
    record = page["records"][0]
    assert (record["magazineTitle"], record["issueNumber"]) == ("National Geographic", "2025-01")
    assert record["data"]["mode"] == "move"


def test_queue_websocket(api: TestClient, env, settings) -> None:
    # Starlette raises when the server closes the socket before accepting.
    with pytest.raises(Exception), api.websocket_connect("/api/v1/ws/queue?apikey=wrong") as ws:  # noqa: B017
        ws.receive_json()
    with api.websocket_connect(f"/api/v1/ws/queue?apikey={settings.auth.api_key}") as ws:
        assert ws.receive_json() == {"type": "queue", "queue": []}
        _grab(api, env["issues"]["2025-01"])  # publishes a change
        message = ws.receive_json()
        assert [d["status"] for d in message["queue"]] == ["queued"]
        assert message["queue"][0]["magazineTitle"] == "National Geographic"


def test_background_import_is_pushed_to_the_websocket(settings, dist, tmp_path: Path) -> None:
    """Regression: the poller must announce imports; the queue page only saw them on the 30 s
    heartbeat because the event bus wasn't passed to the poller."""
    import time

    from magarr.domain.models import DownloadClient, Issue, Magazine, QualityProfile, RootFolder
    from magarr.main import create_app

    settings.downloads.poll_interval = 0.2
    library = tmp_path / "lib"
    library.mkdir()
    source = tmp_path / "dl" / "NG"
    source.mkdir(parents=True)
    (source / "ng.pdf").write_bytes(b"pdf")
    with (
        respx.mock(assert_all_called=False) as mock,
        TestClient(create_app(settings, frontend_dist=dist)) as client,
    ):
        mock.route(host="sab.local").mock(return_value=httpx.Response(200, json={"status": True}))
        with client.app.state.session_factory() as s:
            root = RootFolder(path=str(library), is_default=True)
            s.add(root)
            s.flush()
            magazine = Magazine(
                title="NG", sort_title="ng", folder="NG", quality_profile_id=s.query(QualityProfile).first().id,
                root_folder_id=root.id, alternate_titles=[], tags=[], language="en", frequency="monthly", monitored=True,
            )  # fmt: skip
            s.add(magazine)
            s.flush()
            issue = Issue(
                magazine_id=magazine.id,
                issue_number="1",
                sort_index=1,
                monitored=True,
                status="wanted",
            )
            row = DownloadClient(
                name="SAB",
                implementation="sabnzbd",
                settings={"host": "sab.local", "port": 8080, "api_key": "k"},
            )
            s.add_all([issue, row])
            s.flush()
            s.add(
                Download(
                    issue_id=issue.id,
                    download_client_id=row.id,
                    external_id="x",
                    title="NG.1",
                    protocol="usenet",
                    release={},
                    status="pending_import",
                    output_path=str(source),
                )
            )
            s.commit()
        with client.websocket_connect(f"/api/v1/ws/queue?apikey={settings.auth.api_key}") as ws:
            snapshot = ws.receive_json()["queue"]
            started = time.monotonic()
            while snapshot:
                snapshot = ws.receive_json()["queue"]
            assert time.monotonic() - started < 10  # pushed on import, not the 30 s heartbeat
        assert (library / "NG").exists()


def test_replacing_a_file_removes_the_emptied_folder(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path
) -> None:
    """Moving from a year-folder layout to flat must not leave an empty "2025" folder behind."""
    issue = env["issues"]["2025-01"]
    folder = library_dir / "National Geographic (1888)"
    old = folder / "2025" / "NG 2025-01.epub"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old epub")
    api.post("/api/v1/library/scan", json={})
    _grab(api, issue)
    _complete(sab, downloads, {"ng.pdf": b"new pdf"})
    _poll(api)
    assert (folder / "National Geographic - 2025-01 - Issue 2025-01.pdf").exists()
    assert not (folder / "2025").exists()
    assert folder.exists()  # the magazine folder itself stays


def _refuse_moves(monkeypatch: pytest.MonkeyPatch, times: int) -> list[Path]:
    """Make the first ``times`` transfers fail the way an SMB share does while the download
    client still has the file open."""
    from magarr.importers import importer

    real, refused = importer.transfer, []

    def transfer(src, dest, mode):
        if len(refused) < times:
            refused.append(src)
            raise PermissionError(errno.EACCES, "Permission denied", str(src))
        return real(src, dest, mode)

    monkeypatch.setattr(importer, "transfer", transfer)
    return refused


def test_file_still_in_use_is_retried_on_the_next_poll(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path, monkeypatch
) -> None:
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    source = _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _refuse_moves(monkeypatch, times=1)

    _poll(api)
    [waiting] = api.get("/api/v1/queue").json()
    assert waiting["status"] == "pending_import"
    assert waiting["message"].startswith("Waiting for the file to become available")
    assert (source / "ng.pdf").exists()

    _poll(api)
    assert _issue(api, issue)["status"] == "downloaded"
    assert api.get("/api/v1/queue").json() == []


def test_file_errors_that_persist_block_with_a_hint(
    api: TestClient, env, sab: FakeSab, downloads: Path, monkeypatch
) -> None:
    _grab(api, env["issues"]["2025-01"])
    _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _refuse_moves(monkeypatch, times=100)
    _poll(api)
    with api.app.state.session_factory() as session:  # completed 11 minutes ago
        download = session.query(Download).one()
        download.completed_at = datetime.now(UTC) - timedelta(minutes=11)
        session.commit()
    _poll(api)
    [blocked] = api.get("/api/v1/queue").json()
    assert blocked["status"] == "import_blocked"
    assert "Permission denied" in blocked["message"]
    assert "can read and delete files in the download folder" in blocked["message"]


def test_read_only_download_is_imported_as_a_copy(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path, monkeypatch
) -> None:
    """SABnzbd on a NAS writes as its own user: Magarr can read the files but not move them."""
    from magarr.importers import fileops

    real_replace, real_unlink = os.replace, Path.unlink

    def replace(a, b):
        if downloads in Path(a).parents:
            raise PermissionError(errno.EACCES, "Permission denied", str(a))
        return real_replace(a, b)

    def unlink(self, missing_ok=False):
        if downloads in self.parents:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(fileops.os, "replace", replace)
    monkeypatch.setattr(Path, "unlink", unlink)
    issue = env["issues"]["2025-01"]
    _grab(api, issue)
    source = _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _poll(api)

    assert _issue(api, issue)["status"] == "downloaded"
    assert (source / "ng.pdf").exists()  # left for the user (or SABnzbd) to delete
    [event] = [
        h for h in api.get("/api/v1/history").json()["records"] if h["eventType"] == "imported"
    ]
    assert event["data"]["mode"] == "copy"
    with api.app.state.session_factory() as session:
        download = session.query(Download).one()
        assert download.status == "imported"
        assert download.message.startswith("Imported as a copy")


def test_importing_clears_the_monitored_flag(
    api: TestClient, env, sab: FakeSab, downloads: Path, library_dir: Path
) -> None:
    issue = env["issues"]["2025-01"]
    assert issue["monitored"] is True
    _grab(api, issue)
    _complete(sab, downloads, {"ng.pdf": b"pdf"})
    _poll(api)
    imported = _issue(api, issue)
    assert (imported["status"], imported["monitored"]) == ("downloaded", False)

    # If the file later disappears, the issue is missing, not wanted: it isn't fetched again.
    for path in (library_dir / env["magazine"]["folder"]).rglob("*.pdf"):
        path.unlink()
    api.post("/api/v1/library/scan", json={})
    assert _issue(api, issue)["status"] == "missing"
