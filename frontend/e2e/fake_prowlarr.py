"""Fake Prowlarr, Newznab indexer and SABnzbd for end-to-end tests (stdlib only).

  /api/v1/system/status, /api/v1/indexer, /1/api   Prowlarr with one Torznab indexer (fixtures)
  /usenet/api, /usenet/get/<n>.nzb                  a Newznab indexer serving NZBs. Searches (q=...)
                                                     return USENET_TITLES; the RSS feed (no q) holds
                                                     an unrelated release plus whatever was posted
  POST /control/post?title=...                       "upload" a new release to the RSS feed
  POST /api/webhooks/<id>/<token>                    a Discord webhook; GET /control/discord lists
                                                     what it received
  /sabnzbd/api                                       SABnzbd: added items download over a few polls,
                                                     then a PDF lands in $E2E_DIR/nas/usenet/complete
                                                     (reported as /data/usenet/complete, like a NAS)
Usage: python fake_prowlarr.py <port>
"""

import json
import os
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures"
API_KEY = "e2e-prowlarr-key"

INDEXERS = [
    {
        "id": 1,
        "name": "Fake Tracker",
        "protocol": "torrent",
        "enable": True,
        "priority": 25,
        "capabilities": {"categories": [{"id": 7000, "name": "Books", "subCategories": [{"id": 7010, "name": "Books/Mags"}]}]},
    }
]


USENET_TITLES = ["National.Geographic.2025.01.True.PDF", "National.Geographic.2025.02.True.PDF"]
# Never empty (an empty feed makes Magarr fall back to per-magazine searches).
RSS_TITLES = ["Some.Other.Magazine.2025.01.PDF"]


def newznab_feed(base: str, titles: list[str], prefix: str = "usenet") -> bytes:
    items = "".join(
        f"""<item><title>{title}</title><guid>{prefix}-{n}</guid><link>{base}/usenet/get/{n}.nzb</link>
<pubDate>Wed, 08 Jan 2025 10:15:00 +0000</pubDate>
<newznab:attr name="size" value="52428800"/><newznab:attr name="category" value="7010"/></item>"""
        for n, title in enumerate(titles)
    )
    return (
        '<?xml version="1.0"?><rss xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">'
        f'<channel><newznab:response offset="0" total="{len(titles)}"/>{items}</channel></rss>'
    ).encode()


class FakeSab:
    """Items sit queued for one poll, download over two, then complete."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def add(self, name: str) -> str:
        nzo = f"SABnzbd_nzo_e2e{len(self.items) + 1}"
        self.items[nzo] = {"name": name, "polls": 0}
        return nzo

    def queue(self) -> dict:
        slots = []
        for nzo, item in self.items.items():
            item["polls"] += 1
            if item["polls"] <= 3:
                left = {1: 50, 2: 25, 3: 5}[item["polls"]]
                status = "Queued" if item["polls"] == 1 else "Downloading"
                slots.append({"nzo_id": nzo, "filename": item["name"], "status": status, "mb": "50", "mbleft": str(left)})
        return {"queue": {"paused": False, "slots": slots}}

    def history(self) -> dict:
        slots = []
        for nzo, item in self.items.items():
            if item["polls"] <= 3:
                continue
            self._write_files(item["name"])
            slots.append({"nzo_id": nzo, "name": item["name"], "status": "Completed", "bytes": 52428800, "storage": f"/data/usenet/complete/{item['name']}"})
        return {"history": {"slots": slots}}

    @staticmethod
    def _write_files(name: str) -> None:
        folder = os.path.join(os.environ["E2E_DIR"], "nas", "usenet", "complete", name)
        if not os.path.exists(folder):
            os.makedirs(folder)
            with open(os.path.join(folder, f"{name}.pdf"), "wb") as f:
                f.write(b"%PDF-1.4 fake magazine for " + name.encode())
            with open(os.path.join(folder, "file_id.diz"), "wb") as f:
                f.write(b"junk")


SAB = FakeSab()
DISCORD: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: object) -> None:
        self._send(200, json.dumps(data).encode(), "application/json")

    def _sab(self, params: dict, body: bytes = b"") -> None:
        mode = params.get("mode")
        if mode == "version":
            return self._json({"version": "4.9.9-fake"})
        if params.get("apikey") != API_KEY:
            return self._json({"status": False, "error": "API Key Incorrect"})
        if mode == "get_cats":
            return self._json({"categories": ["*", "magazines"]})
        if mode == "addfile":
            if b"<nzb" not in body:
                return self._json({"status": False, "error": "Not an NZB"})
            return self._json({"status": True, "nzo_ids": [SAB.add(params.get("nzbname", "?"))]})
        if mode in ("queue", "history") and params.get("name") == "delete":
            SAB.items.pop(params.get("value", ""), None)  # Magarr forgetting an imported item
            return self._json({"status": True})
        if mode == "queue":
            return self._json(SAB.queue())
        if mode == "history":
            return self._json(SAB.history())
        return self._send(400, b"{}", "application/json")

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if url.path == "/sabnzbd/api":
            return self._sab(params, body)
        if url.path.startswith("/api/webhooks/"):
            DISCORD.append(json.loads(body))
            return self._send(204, b"", "application/json")
        if url.path == "/control/post":
            RSS_TITLES.append(params["title"])
            return self._json({"posted": params["title"]})
        self._send(404, b"not found", "text/plain")

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/sabnzbd/api":
            return self._sab(params)
        if url.path == "/usenet/api":
            if params.get("t") == "caps":
                return self._send(200, (FIXTURES / "newznab_caps.xml").read_bytes(), "application/xml")
            base = f"http://{self.headers.get('Host')}"
            if "q" in params:
                return self._send(200, newznab_feed(base, USENET_TITLES), "application/xml")
            return self._send(200, newznab_feed(base, RSS_TITLES, "rss"), "application/xml")
        if url.path.startswith("/usenet/get/"):
            return self._send(200, (FIXTURES / "sample.nzb").read_bytes(), "application/x-nzb")
        if url.path == "/control/discord":
            return self._json(DISCORD)
        if url.path == "/ping":
            return self._send(200, b'{"status":"OK"}', "application/json")
        if url.path.startswith("/api/v1/"):
            if self.headers.get("X-Api-Key") != API_KEY:
                return self._send(401, b"{}", "application/json")
            if url.path == "/api/v1/system/status":
                return self._send(200, json.dumps({"appName": "Prowlarr", "version": "1.99.0-fake"}).encode(), "application/json")
            if url.path == "/api/v1/indexer":
                return self._send(200, json.dumps(INDEXERS).encode(), "application/json")
        if url.path == "/1/api":
            if params.get("apikey") != API_KEY:
                return self._send(200, (FIXTURES / "newznab_error.xml").read_bytes(), "application/xml")
            name = "newznab_caps.xml" if params.get("t") == "caps" else "torznab_search.xml"
            return self._send(200, (FIXTURES / name).read_bytes(), "application/xml")
        self._send(404, b"not found", "text/plain")

    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass


class Server(ThreadingHTTPServer):
    def server_bind(self) -> None:
        # HTTPServer.server_bind does a reverse-DNS lookup (getfqdn) that can hang for
        # a long time on some networks; it's pointless for a localhost test server.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


if __name__ == "__main__":
    Server(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
