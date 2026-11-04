import asyncio

import httpx
import pytest
import respx

from magarr.downloaders.base import ClientItemStatus, DownloadClientError, GrabPayload
from magarr.downloaders.bencode import BencodeError, info_hash, magnet_hash
from magarr.downloaders.qbittorrent import QbittorrentClient, QbittorrentSettings
from magarr.downloaders.sabnzbd import SabnzbdClient, SabnzbdSettings
from tests.indexer_fakes import fixture
from tests.torrent_utils import make_torrent

SAB = "http://sab.local:8080/api"
QB = "http://qb.local:8080"


def run(make, coro_fn):
    async def go():
        async with httpx.AsyncClient() as http:
            return await coro_fn(make(http))

    return asyncio.run(go())


def sab(http, **overrides):
    return SabnzbdClient(
        SabnzbdSettings(**{"host": "sab.local", "api_key": "SABKEY", **overrides}), http
    )


def qb(http, **overrides):
    return QbittorrentClient(
        QbittorrentSettings(**{"host": "qb.local", "password": "pw", **overrides}), http
    )


# --- bencode ----------------------------------------------------------------------------------


def test_info_hash_matches_info_dict() -> None:
    torrent, expected = make_torrent("ng.pdf", b"x" * 40000)
    assert info_hash(torrent) == expected


@pytest.mark.parametrize("data", [b"", b"not a torrent", b"d4:spam4:eggse", b"d4:info"])
def test_info_hash_rejects_bad_data(data: bytes) -> None:
    with pytest.raises(BencodeError):
        info_hash(data)


def test_magnet_hash_hex_and_base32() -> None:
    hex_hash = "c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
    assert magnet_hash(f"magnet:?xt=urn:btih:{hex_hash.upper()}&dn=x") == hex_hash
    assert magnet_hash("magnet:?xt=urn:btih:YEX6DQDLXISUVHOJ6UM3GNNKPQJWPKEK") == hex_hash
    assert magnet_hash("magnet:?dn=nothing") is None


# --- SABnzbd ----------------------------------------------------------------------------------


def _sab_router(request: httpx.Request) -> httpx.Response:
    mode = request.url.params["mode"]
    if mode == "version":
        return httpx.Response(200, json={"version": "5.1.3"})
    if request.url.params.get("apikey") != "SABKEY":
        return httpx.Response(200, json={"status": False, "error": "API Key Incorrect"})
    if mode == "get_cats":
        return httpx.Response(200, json={"categories": ["*", "books", "magazines"]})
    if mode == "queue":
        return httpx.Response(200, json={"queue": {"paused": False, "slots": [
            {"nzo_id": "SABnzbd_nzo_a", "filename": "A", "status": "Downloading", "mb": "100", "mbleft": "25", "cat": "magazines"},
            {"nzo_id": "SABnzbd_nzo_b", "filename": "B", "status": "Queued", "mb": "50", "mbleft": "50", "cat": "magazines"},
            {"nzo_id": "SABnzbd_nzo_other", "filename": "Not ours", "status": "Downloading", "mb": "1", "mbleft": "1"},
        ]}})  # fmt: skip
    if mode == "history":
        return httpx.Response(200, json={"history": {"slots": [
            {"nzo_id": "SABnzbd_nzo_c", "name": "C", "status": "Completed", "bytes": 1048576, "storage": "/dl/magazines/C"},
            {"nzo_id": "SABnzbd_nzo_d", "name": "D", "status": "Failed", "bytes": 0, "fail_message": "Out of retention"},
            {"nzo_id": "SABnzbd_nzo_e", "name": "E", "status": "Extracting", "bytes": 5},
        ]}})  # fmt: skip
    if mode == "addfile":
        return httpx.Response(200, json={"status": True, "nzo_ids": ["SABnzbd_nzo_new"]})
    return httpx.Response(404)


@respx.mock
def test_sab_test_warns_about_category_and_pause() -> None:
    respx.get(SAB).mock(side_effect=_sab_router)
    outcome = run(lambda h: sab(h, category="magazines"), lambda c: c.test())
    assert outcome.version == "5.1.3"
    assert outcome.warnings == []

    def paused(request: httpx.Request) -> httpx.Response:
        if request.url.params["mode"] == "queue":
            return httpx.Response(200, json={"queue": {"paused": True, "slots": []}})
        return _sab_router(request)

    respx.get(SAB).mock(side_effect=paused)
    outcome = run(lambda h: sab(h, category="mags"), lambda c: c.test())
    assert len(outcome.warnings) == 2
    assert "Category 'mags' does not exist" in outcome.warnings[0]
    assert "paused" in outcome.warnings[1]


@respx.mock
def test_sab_bad_key() -> None:
    respx.get(SAB).mock(side_effect=_sab_router)
    with pytest.raises(DownloadClientError, match="API Key Incorrect"):
        run(lambda h: sab(h, api_key="WRONG"), lambda c: c.test())


@respx.mock
def test_sab_add_uploads_the_nzb() -> None:
    route = respx.post(SAB).mock(side_effect=_sab_router)
    nzb = fixture("sample.nzb")
    payload = GrabPayload(title="National.Geographic.UK.2025.01", filename="ng.nzb", content=nzb)
    nzo = run(lambda h: sab(h, category="magazines", priority="high"), lambda c: c.add(payload))
    assert nzo == "SABnzbd_nzo_new"
    request = route.calls[0].request
    assert request.url.params["mode"] == "addfile"
    assert request.url.params["cat"] == "magazines"
    assert request.url.params["priority"] == "1"
    assert request.url.params["nzbname"] == "National.Geographic.UK.2025.01"
    assert nzb in request.content  # multipart body carries the NZB


@respx.mock
def test_sab_items_maps_queue_and_history() -> None:
    respx.get(SAB).mock(side_effect=_sab_router)
    ids = {
        "SABnzbd_nzo_a",
        "SABnzbd_nzo_b",
        "SABnzbd_nzo_c",
        "SABnzbd_nzo_d",
        "SABnzbd_nzo_e",
        "SABnzbd_nzo_gone",
    }
    items = run(sab, lambda c: c.items(ids))
    assert set(items) == ids - {"SABnzbd_nzo_gone"}
    a = items["SABnzbd_nzo_a"]
    assert (a.status, a.progress, a.size, a.size_left) == (
        ClientItemStatus.DOWNLOADING,
        0.75,
        100 * 1048576,
        25 * 1048576,
    )
    assert items["SABnzbd_nzo_b"].status is ClientItemStatus.QUEUED
    c = items["SABnzbd_nzo_c"]
    assert (c.status, c.output_path, c.progress) == (
        ClientItemStatus.COMPLETED,
        "/dl/magazines/C",
        1.0,
    )
    d = items["SABnzbd_nzo_d"]
    assert (d.status, d.message) == (ClientItemStatus.FAILED, "Out of retention")
    e = items["SABnzbd_nzo_e"]
    assert (e.status, e.message) == (ClientItemStatus.DOWNLOADING, "Post-processing: Extracting")


@respx.mock
def test_sab_paused_queue_reports_paused() -> None:
    def router(request: httpx.Request) -> httpx.Response:
        if request.url.params["mode"] == "queue":
            return httpx.Response(200, json={"queue": {"paused": True, "slots": [
                {"nzo_id": "x", "filename": "X", "status": "Queued", "mb": "10", "mbleft": "10"}]}})  # fmt: skip
        return httpx.Response(200, json={"history": {"slots": []}})

    respx.get(SAB).mock(side_effect=router)
    assert run(sab, lambda c: c.items({"x"}))["x"].status is ClientItemStatus.PAUSED


@respx.mock
def test_sab_unreachable() -> None:
    respx.get(SAB).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(DownloadClientError, match="Could not reach SABnzbd"):
        run(sab, lambda c: c.test())


# --- qBittorrent ------------------------------------------------------------------------------


def _qb_routes(torrents: list[dict] | None = None, login_ok: bool = True):
    respx.post(f"{QB}/api/v2/auth/login").mock(
        return_value=httpx.Response(
            200, text="Ok." if login_ok else "Fails.", headers={"set-cookie": "SID=abc; path=/"}
        )
    )
    respx.get(f"{QB}/api/v2/app/version").mock(return_value=httpx.Response(200, text="v5.0.2"))
    respx.post(f"{QB}/api/v2/torrents/createCategory").mock(return_value=httpx.Response(409))
    add = respx.post(f"{QB}/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Ok."))
    respx.get(f"{QB}/api/v2/torrents/info").mock(
        return_value=httpx.Response(200, json=torrents or [])
    )
    return add


@respx.mock
def test_qb_test_and_bad_login() -> None:
    _qb_routes()
    assert run(qb, lambda c: c.test()).version == "v5.0.2"
    respx.reset()
    _qb_routes(login_ok=False)
    with pytest.raises(DownloadClientError, match="username or password"):
        run(qb, lambda c: c.test())


@respx.mock
def test_qb_add_torrent_returns_info_hash() -> None:
    add = _qb_routes()
    torrent, expected = make_torrent("ng.pdf", b"y" * 1000)
    payload = GrabPayload(title="NG", filename="ng.torrent", content=torrent)
    ihash = run(lambda h: qb(h, category="magazines", add_paused=True), lambda c: c.add(payload))
    assert ihash == expected
    body = add.calls[0].request.content
    assert torrent in body
    assert b'name="category"' in body and b"magazines" in body
    assert b'name="paused"' in body


@respx.mock
def test_qb_add_magnet_and_invalid_torrent() -> None:
    add = _qb_routes()
    magnet = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a&dn=NG"
    payload = GrabPayload(title="NG", filename="ng", magnet=magnet)
    assert run(qb, lambda c: c.add(payload)) == "c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
    assert b"urls=magnet%3A%3Fxt%3Durn%3Abtih%3Ac12fe" in add.calls[0].request.content
    with pytest.raises(DownloadClientError, match="Not a valid torrent"):
        run(qb, lambda c: c.add(GrabPayload(title="x", filename="x", content=b"<html>")))


@respx.mock
def test_qb_items_state_mapping() -> None:
    torrents = [
        {"hash": "AA", "name": "dl", "state": "downloading", "progress": 0.5, "size": 100, "amount_left": 50},
        {"hash": "bb", "name": "seed", "state": "stalledUP", "progress": 1, "size": 100, "amount_left": 0, "content_path": "/dl/seed"},
        {"hash": "cc", "name": "err", "state": "error", "progress": 0.2, "size": 100, "amount_left": 80},
        {"hash": "dd", "name": "stopped", "state": "stoppedDL", "progress": 0.1, "size": 100, "amount_left": 90},
        {"hash": "ee", "name": "q", "state": "queuedDL", "progress": 0, "size": 100, "amount_left": 100},
        {"hash": "ff", "name": "done-paused", "state": "pausedUP", "progress": 1, "size": 100, "amount_left": 0},
    ]  # fmt: skip
    _qb_routes(torrents)
    items = run(qb, lambda c: c.items({"aa", "bb", "cc", "dd", "ee", "ff", "zz"}))
    status = {k: v.status for k, v in items.items()}
    assert status == {
        "aa": ClientItemStatus.DOWNLOADING,
        "bb": ClientItemStatus.COMPLETED,
        "cc": ClientItemStatus.FAILED,
        "dd": ClientItemStatus.PAUSED,
        "ee": ClientItemStatus.QUEUED,
        "ff": ClientItemStatus.COMPLETED,
    }
    assert items["bb"].output_path == "/dl/seed"
    assert items["cc"].message == "qBittorrent state: error"


# --- NZBGet -----------------------------------------------------------------------------------

NZBGET = "http://nzbget.local:6789/jsonrpc"


def nzbget(http, **overrides):
    from magarr.downloaders.nzbget import NzbgetClient, NzbgetSettings

    return NzbgetClient(
        NzbgetSettings(**{"host": "nzbget.local", "password": "pw", **overrides}), http
    )


def _nzbget_router(calls: list):
    import base64
    import json

    def router(request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(b"nzbget:pw").decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401)
        body = json.loads(request.content)
        calls.append(body)
        method = body["method"]
        result = {
            "version": "24.3",
            "config": [
                {"Name": "Category1.Name", "Value": "magazines"},
                {"Name": "MainDir", "Value": "/data"},
            ],
            "append": 42,
            "listgroups": [
                {
                    "NZBID": 1,
                    "NZBName": "A",
                    "Status": "DOWNLOADING",
                    "FileSizeMB": 100,
                    "RemainingSizeMB": 40,
                    "Category": "magazines",
                },
                {
                    "NZBID": 2,
                    "NZBName": "B",
                    "Status": "UNPACKING",
                    "FileSizeMB": 10,
                    "RemainingSizeMB": 0,
                },
                {
                    "NZBID": 3,
                    "NZBName": "C",
                    "Status": "PAUSED",
                    "FileSizeMB": 10,
                    "RemainingSizeMB": 10,
                },
            ],
            "history": [
                {
                    "NZBID": 4,
                    "Name": "D",
                    "Status": "SUCCESS/UNPACK",
                    "FileSizeMB": 50,
                    "FinalDir": "",
                    "DestDir": "/data/complete/D",
                    "DeleteStatus": "NONE",
                },
                {
                    "NZBID": 5,
                    "Name": "E",
                    "Status": "FAILURE/PAR",
                    "FileSizeMB": 50,
                    "DestDir": "/data/complete/E",
                    "DeleteStatus": "NONE",
                },
                {
                    "NZBID": 6,
                    "Name": "F",
                    "Status": "DELETED/MANUAL",
                    "FileSizeMB": 50,
                    "DeleteStatus": "MANUAL",
                },
            ],
            "editqueue": True,
        }[method]
        return httpx.Response(200, json={"version": "1.1", "result": result})

    return router


@respx.mock
def test_nzbget_test_add_and_items() -> None:
    calls: list = []
    respx.post(NZBGET).mock(side_effect=_nzbget_router(calls))
    outcome = run(lambda h: nzbget(h, category="magazines"), lambda c: c.test())
    assert (outcome.version, outcome.warnings) == ("24.3", [])
    warn = run(lambda h: nzbget(h, category="mags"), lambda c: c.test())
    assert "Category 'mags' does not exist" in warn.warnings[0]

    payload = GrabPayload(title="NG", filename="ng.nzb", content=fixture("sample.nzb"))
    assert (
        run(lambda h: nzbget(h, category="magazines", priority="high"), lambda c: c.add(payload))
        == "42"
    )
    append = next(c for c in calls if c["method"] == "append")
    import base64

    assert append["params"][0] == "ng.nzb"
    assert base64.b64decode(append["params"][1]) == fixture("sample.nzb")
    assert append["params"][2:4] == ["magazines", 50]

    items = run(nzbget, lambda c: c.items({"1", "2", "3", "4", "5", "6", "99"}))
    assert {k: v.status for k, v in items.items()} == {
        "1": ClientItemStatus.DOWNLOADING,
        "2": ClientItemStatus.DOWNLOADING,
        "3": ClientItemStatus.PAUSED,
        "4": ClientItemStatus.COMPLETED,
        "5": ClientItemStatus.FAILED,
        "6": ClientItemStatus.FAILED,
    }
    assert items["1"].progress == 0.6
    assert items["2"].message == "Post-processing: unpacking"
    assert items["4"].output_path == "/data/complete/D"  # FinalDir empty -> DestDir
    assert items["5"].message == "NZBGet: FAILURE/PAR"


@respx.mock
def test_nzbget_bad_login() -> None:
    respx.post(NZBGET).mock(side_effect=_nzbget_router([]))
    with pytest.raises(DownloadClientError, match="username or password"):
        run(lambda h: nzbget(h, password="wrong"), lambda c: c.test())
