"""Phase 6: grab -> real Transmission / Deluge / rTorrent -> complete -> imported.

Run with scripts/torrent-clients-integration.sh. As in the qBittorrent test, Magarr makes its own
torrent for a local file and pre-places the data where the client downloads, so each client
verifies it on add and completes without any network transfer.
"""

import os
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.domain.models import Download
from magarr.pipeline.tracking import poll_once
from tests.torrent_utils import make_torrent

WORK = os.environ.get("MAGARR_TC_WORK")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not WORK, reason="needs the containers (scripts/torrent-clients-integration.sh)"
    ),
]
TORZNAB = "https://tracker.example/api"
TITLE = "National.Geographic.UK.2025.01.HQ.PDF"

CLIENTS = {
    "transmission": {"port": 9191, "username": "magarr", "password": "magarr-test", "directory": "/downloads"},
    "deluge": {"port": 8212, "password": "deluge", "directory": "/downloads"},
    "rtorrent": {"port": 8100, "directory": "/downloads"},
}  # fmt: skip


def _torznab(link: str) -> bytes:
    return f"""<?xml version="1.0"?><rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>
<item><title>{TITLE}</title><guid>t1</guid><link>{link}</link><size>65536</size>
<pubDate>Wed, 08 Jan 2025 10:15:00 +0000</pubDate>
<torznab:attr name="seeders" value="5"/><torznab:attr name="peers" value="5"/></item>
</channel></rss>""".encode()


def _poll(api: TestClient):
    async def go():
        with api.app.state.session_factory() as session:
            return await poll_once(session, api.app.state.indexer_runtime)

    return api.portal.call(go)


@pytest.mark.parametrize("implementation", list(CLIENTS))
def test_grab_complete_and_import(
    api: TestClient, magazine: dict, library_dir: Path, implementation: str
) -> None:
    downloads = Path(WORK) / implementation / "downloads"
    content = os.urandom(64 * 1024)
    torrent, info_hash = make_torrent(f"{TITLE}.pdf", content)
    (downloads / f"{TITLE}.pdf").write_bytes(content)  # the client will find it complete

    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="127.0.0.1").pass_through()  # the client is real
        mock.get(TORZNAB).mock(
            return_value=httpx.Response(
                200, content=_torznab("https://tracker.example/dl/1.torrent")
            )
        )
        mock.get("https://tracker.example/dl/1.torrent").mock(
            return_value=httpx.Response(200, content=torrent)
        )
        api.post(
            "/api/v1/indexer",
            json={"name": "Tracker", "implementation": "torznab", "baseUrl": "https://tracker.example",
                  "apiKey": "k", "requestInterval": 0},
        )  # fmt: skip
        client = api.post(
            "/api/v1/downloadclient",
            json={"name": implementation, "implementation": implementation,
                  "settings": {"host": "127.0.0.1", **CLIENTS[implementation]}},
        ).json()  # fmt: skip
        test = api.post(f"/api/v1/downloadclient/{client['id']}/test").json()
        assert test["ok"], test
        api.post(
            "/api/v1/remotepathmapping",
            json={"host": "127.0.0.1", "remotePath": "/downloads", "localPath": str(downloads)},
        )
        issue = api.post(
            "/api/v1/issue",
            json={"magazineId": magazine["id"], "issueNumber": "2025-01", "publishDate": "2025-01-01",
                  "monitored": True},
        ).json()  # fmt: skip
        [release] = [
            r
            for r in api.post(f"/api/v1/issue/{issue['id']}/search").json()["releases"]
            if not r["rejected"]
        ]
        grabbed = api.post(
            "/api/v1/release/grab",
            json={
                "guid": release["guid"],
                "indexerId": release["indexerId"],
                "issueId": issue["id"],
            },
        )
        assert grabbed.status_code == 201, grabbed.text
        with api.app.state.session_factory() as session:
            [download] = session.query(Download).all()
            assert download.external_id == info_hash  # the hash Magarr computed is the client's

        imported = None
        for _ in range(90):
            _poll(api)
            imported = api.get(f"/api/v1/issue/{issue['id']}").json()
            if imported["status"] == "downloaded":
                break
            time.sleep(0.5)
        assert imported["status"] == "downloaded", api.get("/api/v1/queue").json()

        expected = (
            library_dir
            / "National Geographic (1888)"
            / "National Geographic - 2025-01 - Issue 2025-01.pdf"
        )
        assert expected.read_bytes() == content
        assert (downloads / f"{TITLE}.pdf").exists()  # torrents keep seeding
