"""Phase 3 + 4 definitions of done against a real qBittorrent (scripts/qbittorrent-integration.sh).

grab -> qBittorrent -> complete -> imported into the library with the naming scheme, through a
remote path mapping (qBittorrent's /downloads is the host folder). The test makes its own torrent for a
local file and pre-places the data in qBittorrent's downloads folder; qBittorrent verifies it on
add, so it completes without any network transfer.
"""

import os
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.pipeline.tracking import poll_once
from tests.torrent_utils import make_torrent

QBT_URL = os.environ.get("MAGARR_QBT_URL")
DOWNLOADS = os.environ.get("MAGARR_QBT_DOWNLOADS")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not QBT_URL, reason="needs a qBittorrent container (scripts/qbittorrent-integration.sh)"
    ),
]
TORZNAB = "https://tracker.example/api"
TITLE = "National.Geographic.UK.2025.01.HQ.PDF"


def _torznab(link: str) -> bytes:
    return f"""<?xml version="1.0"?><rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>
<item><title>{TITLE}</title><guid>t1</guid><link>{link}</link><size>65536</size>
<pubDate>Wed, 08 Jan 2025 10:15:00 +0000</pubDate>
<torznab:attr name="seeders" value="5"/><torznab:attr name="peers" value="5"/></item>
</channel></rss>""".encode()


def _poll(api: TestClient):
    """Poll on the app's own event loop: its shared HTTP client belongs to that loop."""

    async def go():
        with api.app.state.session_factory() as session:
            return await poll_once(session, api.app.state.indexer_runtime)

    return api.portal.call(go)


def test_grab_complete_and_import_with_real_qbittorrent(
    api: TestClient, magazine: dict, library_dir: Path
) -> None:
    content = os.urandom(64 * 1024)
    torrent, info_hash = make_torrent(f"{TITLE}.pdf", content)
    (Path(DOWNLOADS) / f"{TITLE}.pdf").write_bytes(content)  # qBittorrent will find it complete

    host, port = QBT_URL.removeprefix("http://").split(":")
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host=host).pass_through()  # qBittorrent is real
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
            json={
                "name": "Tracker",
                "implementation": "torznab",
                "baseUrl": "https://tracker.example",
                "apiKey": "k",
                "requestInterval": 0,
            },
        )
        client = api.post(
            "/api/v1/downloadclient",
            json={
                "name": "qBittorrent",
                "implementation": "qbittorrent",
                "settings": {
                    "host": host,
                    "port": int(port),
                    "username": "admin",
                    "password": "magarr-test",
                    "category": "",
                },
            },
        ).json()
        test = api.post(f"/api/v1/downloadclient/{client['id']}/test").json()
        assert test["ok"], test
        # qBittorrent reports paths inside its container; map them to the host folder.
        api.post(
            "/api/v1/remotepathmapping",
            json={"host": host, "remotePath": "/downloads", "localPath": DOWNLOADS},
        )

        issue = api.post(
            "/api/v1/issue",
            json={
                "magazineId": magazine["id"],
                "issueNumber": "2025-01",
                "publishDate": "2025-01-01",
                "monitored": True,
            },
        ).json()
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
        assert grabbed.json()["status"] == "queued"

        imported = None
        for _ in range(60):
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
        assert imported["file"]["quality"] == "pdf_hires"  # "HQ.PDF" in the release name
        assert (Path(DOWNLOADS) / f"{TITLE}.pdf").exists()  # torrents keep seeding: hard link/copy
        assert api.get("/api/v1/queue").json() == []

        events = [
            e["eventType"]
            for e in api.get(f"/api/v1/history?issueId={issue['id']}").json()["records"]
        ]
        assert events == ["imported", "download_completed", "grabbed"]

        # The torrent qBittorrent holds is the one Magarr computed the hash for.
        with httpx.Client(base_url=QBT_URL, headers={"Referer": QBT_URL}) as http:
            http.post("/api/v2/auth/login", data={"username": "admin", "password": "magarr-test"})
            hashes = [t["hash"] for t in http.get("/api/v2/torrents/info").json()]
        assert hashes == [info_hash]
