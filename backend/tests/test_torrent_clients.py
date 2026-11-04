"""Phase 6: Transmission, Deluge and rTorrent clients against faithful fakes of their APIs."""

import asyncio
import base64
import json
import xmlrpc.client

import httpx
import pytest
import respx

from magarr.downloaders.base import ClientItemStatus, DownloadClientError, GrabPayload
from magarr.downloaders.deluge import DelugeClient, DelugeSettings
from magarr.downloaders.rtorrent import RtorrentClient, RtorrentSettings
from magarr.downloaders.transmission import TransmissionClient, TransmissionSettings
from tests.torrent_utils import make_torrent

TORRENT, HASH = make_torrent("NG.2025.01.pdf", b"x" * 40000)
MAGNET_HASH = "c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
MAGNET = f"magnet:?xt=urn:btih:{MAGNET_HASH}&dn=NG"


def run(client_factory, coro_fn):
    async def go():
        async with httpx.AsyncClient() as http:
            return await coro_fn(client_factory(http))

    return asyncio.run(go())


# --- Transmission ------------------------------------------------------------------------------

TR = "http://tr.local:9091/transmission/rpc"


class FakeTransmission:
    def __init__(self) -> None:
        self.torrents: dict[str, dict] = {}
        self.calls: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("X-Transmission-Session-Id") != "S1":
            return httpx.Response(409, headers={"X-Transmission-Session-Id": "S1"})
        if request.headers.get("authorization") != httpx.BasicAuth("u", "p")._auth_header:
            return httpx.Response(401)
        body = json.loads(request.content)
        self.calls.append(body)
        method, args = body["method"], body["arguments"]
        if method == "session-get":
            return self._ok({"version": "4.0.6", "rpc-version": 17})
        if method == "torrent-add":
            if HASH in self.torrents:
                return self._ok({"torrent-duplicate": {"hashString": HASH}})
            self.torrents[HASH] = {
                "hashString": HASH, "name": "NG.2025.01.pdf", "status": 4, "percentDone": 0.25,
                "totalSize": 40000, "leftUntilDone": 30000, "downloadDir": "/downloads",
                "error": 0, "errorString": "", "labels": args.get("labels", []),
            }  # fmt: skip
            return self._ok({"torrent-added": {"hashString": HASH}})
        if method == "torrent-get":
            return self._ok({"torrents": [t for h, t in self.torrents.items() if h in args["ids"]]})
        if method == "torrent-remove":
            for ihash in args["ids"]:
                self.torrents.pop(ihash, None)
            return self._ok({})
        return httpx.Response(200, json={"result": "method name not recognized"})

    @staticmethod
    def _ok(arguments: dict) -> httpx.Response:
        return httpx.Response(200, json={"result": "success", "arguments": arguments})


def transmission(http, **overrides):
    settings = {"host": "tr.local", "username": "u", "password": "p", "directory": "/downloads"}
    return TransmissionClient(TransmissionSettings(**{**settings, **overrides}), http)


@pytest.fixture
def tr() -> FakeTransmission:
    return FakeTransmission()


def test_transmission_session_handshake_and_version(tr: FakeTransmission) -> None:
    with respx.mock() as mock:
        mock.post(TR).mock(side_effect=tr)
        assert run(transmission, lambda c: c.test()).version == "4.0.6"


def test_transmission_add_track_and_remove(tr: FakeTransmission) -> None:
    async def flow(client):
        ihash = await client.add(GrabPayload(title="NG", filename="ng.torrent", content=TORRENT))
        downloading = (await client.items({ihash}))[ihash]
        tr.torrents[ihash].update(percentDone=1.0, leftUntilDone=0, status=6)
        done = (await client.items({ihash}))[ihash]
        again = await client.add(GrabPayload(title="NG", filename="ng.torrent", content=TORRENT))
        await client.remove(ihash, delete_data=True)
        return ihash, downloading, done, again

    with respx.mock() as mock:
        mock.post(TR).mock(side_effect=tr)
        ihash, downloading, done, again = run(transmission, flow)
    assert ihash == HASH and again == HASH  # a duplicate is tracked, not an error
    add = next(c for c in tr.calls if c["method"] == "torrent-add")["arguments"]
    assert base64.b64decode(add["metainfo"]) == TORRENT
    assert (add["labels"], add["download-dir"], add["paused"]) == (
        ["magazines"],
        "/downloads",
        False,
    )
    assert (downloading.status, downloading.progress) == (ClientItemStatus.DOWNLOADING, 0.25)
    assert done.status is ClientItemStatus.COMPLETED
    assert done.output_path == "/downloads/NG.2025.01.pdf"
    assert done.category == "magazines"
    remove = next(c for c in tr.calls if c["method"] == "torrent-remove")["arguments"]
    assert remove == {"ids": [HASH], "delete-local-data": True}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"status": 0}, ClientItemStatus.PAUSED),
        ({"status": 3}, ClientItemStatus.QUEUED),
        ({"error": 3, "errorString": "No data found"}, ClientItemStatus.FAILED),
        ({"error": 2, "errorString": "Tracker gone"}, ClientItemStatus.DOWNLOADING),
    ],
)
def test_transmission_states(tr: FakeTransmission, change: dict, expected) -> None:
    async def flow(client):
        ihash = await client.add(GrabPayload(title="NG", filename="ng.torrent", content=TORRENT))
        tr.torrents[ihash].update(change)
        return (await client.items({ihash}))[ihash]

    with respx.mock() as mock:
        mock.post(TR).mock(side_effect=tr)
        assert run(transmission, flow).status is expected


def test_transmission_errors(tr: FakeTransmission) -> None:
    with respx.mock() as mock:
        mock.post(TR).mock(side_effect=tr)
        with pytest.raises(DownloadClientError, match="username or password"):
            run(lambda h: transmission(h, password="wrong"), lambda c: c.test())


# --- Deluge ------------------------------------------------------------------------------------

DE = "http://de.local:8112/json"


class FakeDeluge:
    def __init__(self, plugins=("Label",)) -> None:
        self.authed = False
        self.connected = False
        self.plugins = list(plugins)
        self.labels: list[str] = []
        self.torrents: dict[str, dict] = {}
        self.calls: list[tuple[str, list]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        self.calls.append((method, params))
        if method == "auth.login":
            self.authed = params == ["deluge"]
            return self._result(self.authed, body)
        if not self.authed:
            return httpx.Response(
                200,
                json={
                    "result": None,
                    "error": {"message": "Not authenticated", "code": 1},
                    "id": body["id"],
                },
            )
        handlers = {
            "web.connected": lambda: self.connected,
            "web.get_hosts": lambda: [["h1", "127.0.0.1", 58846, "localclient"]],
            "web.connect": lambda: setattr(self, "connected", True),
            "daemon.get_version": lambda: "2.1.1",
            "core.get_enabled_plugins": lambda: self.plugins,
            "label.get_labels": lambda: self.labels,
            "label.add": lambda: self.labels.append(params[0]),
            "label.set_torrent": lambda: self.torrents[params[0]].update(label=params[1]),
            "core.add_torrent_file": lambda: self._add(HASH, params),
            "core.add_torrent_magnet": lambda: self._add(MAGNET_HASH, params),
            "core.get_torrents_status": lambda: {h: t for h, t in self.torrents.items() if h in params[0]["id"]},
            "core.remove_torrent": lambda: self.torrents.pop(params[0]) and True,
        }  # fmt: skip
        if method not in handlers:
            return httpx.Response(
                200,
                json={
                    "result": None,
                    "error": {"message": f"Unknown method {method}", "code": 2},
                    "id": body["id"],
                },
            )
        return self._result(handlers[method](), body)

    def _add(self, ihash: str, params: list) -> str | None:
        if ihash in self.torrents:
            return None
        self.torrents[ihash] = {
            "name": "NG.2025.01.pdf", "state": "Downloading", "progress": 40.0,
            "total_wanted": 40000, "total_done": 16000, "save_path": params[-1].get("download_location", "/root/Downloads"),
            "label": "", "message": "OK",
        }  # fmt: skip
        return ihash

    @staticmethod
    def _result(result, body) -> httpx.Response:
        return httpx.Response(200, json={"result": result, "error": None, "id": body["id"]})


def deluge(http, **overrides):
    settings = {"host": "de.local", "directory": "/downloads"}
    return DelugeClient(DelugeSettings(**{**settings, **overrides}), http)


def test_deluge_logs_in_connects_to_the_daemon_and_labels(monkeypatch) -> None:
    fake = FakeDeluge()

    async def flow(client):
        version = (await client.test()).version
        ihash = await client.add(GrabPayload(title="NG", filename="ng.torrent", content=TORRENT))
        first = (await client.items({ihash}))[ihash]
        fake.torrents[ihash].update(state="Seeding", progress=100.0, total_done=40000)
        done = (await client.items({ihash}))[ihash]
        await client.remove(ihash, delete_data=False)
        return version, ihash, first, done

    with respx.mock() as mock:
        mock.post(DE).mock(side_effect=fake)
        version, ihash, first, done = run(lambda h: deluge(h, category="Magazines"), flow)
    assert version == "2.1.1" and ihash == HASH
    assert ("web.connect", ["h1"]) in fake.calls
    assert fake.labels == ["magazines"]  # Deluge labels are lower case
    add = next(p for m, p in fake.calls if m == "core.add_torrent_file")
    assert base64.b64decode(add[1]) == TORRENT and add[2]["download_location"] == "/downloads"
    assert (first.status, first.progress, first.size_left) == (
        ClientItemStatus.DOWNLOADING,
        0.4,
        24000,
    )
    assert (done.status, done.output_path, done.category) == (
        ClientItemStatus.COMPLETED, "/downloads/NG.2025.01.pdf", "magazines",
    )  # fmt: skip
    assert ("core.remove_torrent", [HASH, False]) in fake.calls


def test_deluge_relogs_in_when_the_session_expires() -> None:
    fake = FakeDeluge()

    async def flow(client):
        await client.test()
        fake.authed = False  # Web UI restarted
        return (await client.test()).version

    with respx.mock() as mock:
        mock.post(DE).mock(side_effect=fake)
        assert run(deluge, flow) == "2.1.1"


def test_deluge_without_the_label_plugin_warns_and_still_adds() -> None:
    fake = FakeDeluge(plugins=())

    async def flow(client):
        outcome = await client.test()
        ihash = await client.add(GrabPayload(title="NG", filename="m", magnet=MAGNET))
        return outcome, ihash

    with respx.mock() as mock:
        mock.post(DE).mock(side_effect=fake)
        outcome, ihash = run(deluge, flow)
    assert "Label plugin is off" in outcome.warnings[0]
    assert ihash == MAGNET_HASH


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Paused", ClientItemStatus.PAUSED),
        ("Queued", ClientItemStatus.QUEUED),
        ("Error", ClientItemStatus.FAILED),
    ],
)
def test_deluge_states(state: str, expected) -> None:
    fake = FakeDeluge()

    async def flow(client):
        ihash = await client.add(GrabPayload(title="NG", filename="ng.torrent", content=TORRENT))
        fake.torrents[ihash]["state"] = state
        return (await client.items({ihash}))[ihash]

    with respx.mock() as mock:
        mock.post(DE).mock(side_effect=fake)
        assert run(deluge, flow).status is expected


def test_deluge_wrong_password() -> None:
    with respx.mock() as mock:
        mock.post(DE).mock(side_effect=FakeDeluge())
        with pytest.raises(DownloadClientError, match="rejected the password"):
            run(lambda h: deluge(h, password="nope"), lambda c: c.test())


# --- rTorrent ----------------------------------------------------------------------------------

RT = "http://rt.local:8080/RPC2"


class FakeRtorrent:
    def __init__(self) -> None:
        self.torrents: dict[str, dict] = {}
        self.calls: list[tuple[str, tuple]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params, method = xmlrpc.client.loads(request.content)
        self.calls.append((method, params))
        if method == "system.client_version":
            return self._ok("0.9.8")
        if method in ("load.raw_start", "load.raw"):
            commands = dict(c.split("=", 1) for c in params[2:])
            self.torrents[HASH.upper()] = {
                "name": "NG.2025.01.pdf", "size": 40000, "left": 30000, "complete": 0,
                "state": int(method == "load.raw_start"), "active": int(method == "load.raw_start"),
                "directory": commands.get("d.directory.set", "/rt"), "label": commands.get("d.custom1.set", ""),
            }  # fmt: skip
            return self._ok(0)
        if method == "d.multicall2":
            rows = [
                [h, t["name"], t["size"], t["left"], t["complete"], t["state"], t["active"], 0, "",
                 f"{t['directory']}/{t['name']}", t["directory"], t["label"]]
                for h, t in self.torrents.items()
            ]  # fmt: skip
            return self._ok(rows)
        if method in ("d.erase", "d.custom5.set"):
            if params[0] not in self.torrents:
                return self._fault("Could not find info-hash.")
            if method == "d.erase":
                del self.torrents[params[0]]
            return self._ok(0)
        return self._fault(f"Method '{method}' not defined")

    @staticmethod
    def _ok(value) -> httpx.Response:
        return httpx.Response(200, content=xmlrpc.client.dumps((value,), methodresponse=True))

    @staticmethod
    def _fault(message: str) -> httpx.Response:
        return httpx.Response(200, content=xmlrpc.client.dumps(xmlrpc.client.Fault(-501, message)))


def rtorrent(http, **overrides):
    settings = {"host": "rt.local", "directory": "/downloads"}
    return RtorrentClient(RtorrentSettings(**{**settings, **overrides}), http)


def test_rtorrent_add_track_and_remove() -> None:
    fake = FakeRtorrent()

    async def flow(client):
        version = (await client.test()).version
        ihash = await client.add(GrabPayload(title="NG", filename="ng.torrent", content=TORRENT))
        first = (await client.items({ihash}))[ihash]
        fake.torrents[ihash.upper()].update(complete=1, left=0)
        done = (await client.items({ihash}))[ihash]
        await client.remove(ihash, delete_data=True)
        return version, ihash, first, done

    with respx.mock() as mock:
        mock.post(RT).mock(side_effect=fake)
        version, ihash, first, done = run(rtorrent, flow)
    assert (version, ihash) == ("0.9.8", HASH)
    _, params = next(c for c in fake.calls if c[0] == "load.raw_start")
    assert params[1].data == TORRENT
    assert params[2:] == ("d.directory.set=/downloads", "d.custom1.set=magazines")
    assert (first.status, first.progress) == (ClientItemStatus.DOWNLOADING, 0.25)
    assert (done.status, done.output_path, done.category) == (
        ClientItemStatus.COMPLETED, "/downloads/NG.2025.01.pdf", "magazines",
    )  # fmt: skip
    assert [m for m, _ in fake.calls[-2:]] == ["d.custom5.set", "d.erase"]  # delete data first
    assert fake.torrents == {}


def test_rtorrent_paused_add_and_faults() -> None:
    fake = FakeRtorrent()

    async def flow(client):
        ihash = await client.add(GrabPayload(title="NG", filename="ng.torrent", content=TORRENT))
        paused = (await client.items({ihash}))[ihash]
        try:
            await client.remove("0" * 40, delete_data=False)
        except DownloadClientError as exc:
            return paused, str(exc)
        return paused, None

    with respx.mock() as mock:
        mock.post(RT).mock(side_effect=fake)
        paused, error = run(lambda h: rtorrent(h, add_paused=True), flow)
    assert paused.status is ClientItemStatus.PAUSED
    assert error == "rTorrent: Could not find info-hash."


def test_rtorrent_rejects_a_non_xmlrpc_reply() -> None:
    with respx.mock() as mock:
        mock.post(RT).mock(return_value=httpx.Response(200, text="<html>ruTorrent</html>"))
        with pytest.raises(DownloadClientError, match="check the URL"):
            run(rtorrent, lambda c: c.test())
