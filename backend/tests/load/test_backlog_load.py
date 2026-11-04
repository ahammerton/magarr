"""Phase 7 load test: backlog search against 20 indexers, rate limits under pressure.

A stand-in Prowlarr serves 20 Newznab indexers (/1/api ... /20/api). Each enforces its own
minimum gap between requests (answering 429 if Magarr is too quick) and records every arrival.
One indexer is slow, one keeps failing, and interactive searches run alongside the backlog.

Run with scripts/load-test.sh (or MAGARR_LOAD=1 pytest -m load tests/load).
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from magarr.domain.models import Indexer, Issue
from magarr.indexers.health import FAILURE_THRESHOLD
from magarr.pipeline.automation import backlog_search

pytestmark = [
    pytest.mark.load,
    pytest.mark.skipif(not os.environ.get("MAGARR_LOAD"), reason="slow: scripts/load-test.sh"),
]

INDEXERS = 20
INTERVAL = 0.25  # seconds between requests to one indexer, enforced by both sides
SLOW, FAILING = 7, 13  # indexer numbers
SLOW_SECONDS = 0.6
ISSUES = 40
FEED = (
    b'<?xml version="1.0"?><rss xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">'
    b'<channel><newznab:response offset="0" total="1"/><item><title>Some.Other.Magazine.2024.01.PDF'
    b'</title><guid>x</guid><link>http://127.0.0.1/x.nzb</link><newznab:attr name="size" '
    b'value="1000"/></item></channel></rss>'
)


class FakeProwlarr:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.arrivals: dict[int, list[float]] = {n: [] for n in range(1, INDEXERS + 1)}
        self.in_flight: dict[int, int] = dict.fromkeys(self.arrivals, 0)
        self.max_in_flight: dict[int, int] = dict.fromkeys(self.arrivals, 0)
        self.too_fast: list[tuple[int, float]] = []
        self.searches: dict[int, list[str]] = {n: [] for n in self.arrivals}

    def handle(self, n: int, params: dict[str, str]) -> tuple[int, bytes]:
        now = time.monotonic()
        with self.lock:
            previous = self.arrivals[n][-1] if self.arrivals[n] else None
            self.arrivals[n].append(now)
            self.in_flight[n] += 1
            self.max_in_flight[n] = max(self.max_in_flight[n], self.in_flight[n])
            if "q" in params:
                self.searches[n].append(params["q"])
        try:
            if previous is not None and now - previous < INTERVAL * 0.95:
                with self.lock:
                    self.too_fast.append((n, now - previous))
                return 429, b"slow down"
            if n == FAILING:
                return 500, b"boom"
            if n == SLOW:
                time.sleep(SLOW_SECONDS)
            return 200, FEED
        finally:
            with self.lock:
                self.in_flight[n] -= 1


@pytest.fixture
def prowlarr():
    fake = FakeProwlarr()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            n = int(url.path.split("/")[1])
            status, body = fake.handle(n, {k: v[0] for k, v in parse_qs(url.query).items()})
            self.send_response(status)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    class Server(ThreadingHTTPServer):
        request_queue_size = 128  # the default (5) refuses 20 indexers connecting at once
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fake, server.server_address[1]
    server.shutdown()


def test_backlog_search_respects_every_indexers_rate_limit(
    api: TestClient, root_folder: dict, prowlarr
) -> None:
    fake, port = prowlarr
    with api.app.state.session_factory() as session:
        for n in range(1, INDEXERS + 1):
            session.add(
                Indexer(name=f"Prowlarr {n}", implementation="newznab", base_url=f"http://127.0.0.1:{port}/{n}/",
                        api_path="/api", api_key="k", categories=[7010], priority=25, enabled=True, tags=[],
                        request_interval=INTERVAL, source="prowlarr")
            )  # fmt: skip
        session.commit()
    issue_ids = []
    for n in range(ISSUES):
        mag = api.post(
            "/api/v1/magazine", json={"title": f"Load Test Magazine {n}", "frequency": "monthly"}
        ).json()
        issue_ids.append(api.post(
            "/api/v1/issue",
            json={"magazineId": mag["id"], "issueNumber": "2024-06", "publishDate": "2024-06-01", "monitored": True},
        ).json()["id"])  # fmt: skip

    # Interactive searches from "the UI" at the same time as the backlog, on the same indexers.
    def interactive() -> list[int]:
        return [api.post(f"/api/v1/issue/{i}/search").status_code for i in issue_ids[-5:]]

    async def backlog():
        with api.app.state.session_factory() as session:
            return await backlog_search(
                session, api.app.state.indexer_runtime, ISSUES, datetime.now(UTC)
            )

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        ui = pool.submit(interactive)
        result = api.portal.call(backlog)
        ui_statuses = ui.result()
    elapsed = time.monotonic() - started

    # The indexers never saw Magarr go too fast, nor two requests at once.
    assert fake.too_fast == []
    assert max(fake.max_in_flight.values()) == 1
    for n, times in fake.arrivals.items():
        gaps = [b - a for a, b in pairwise(times)]
        assert all(g >= INTERVAL * 0.95 for g in gaps), (n, min(gaps))

    # Every issue searched; every healthy indexer asked about each (backlog and UI queries for
    # the same issue share the cache).
    assert result.searched == ISSUES and result.stopped is None
    assert ui_statuses == [200] * 5
    healthy = [n for n in fake.searches if n != FAILING]
    for n in healthy:
        assert len(set(fake.searches[n])) == ISSUES, (n, len(set(fake.searches[n])))
    with api.app.state.session_factory() as session:
        assert all(session.get(Issue, i).last_searched_at for i in issue_ids)

        # The failing indexer was backed off after a few failures instead of being hammered.
        failing = session.query(Indexer).filter_by(name=f"Prowlarr {FAILING}").one()
        assert failing.disabled_until is not None
    assert len(fake.arrivals[FAILING]) <= FAILURE_THRESHOLD + 1

    # Indexers ran in parallel: the slow one set the pace, not the sum of all twenty.
    slowest = ISSUES * (INTERVAL + SLOW_SECONDS)
    print(f"\n{ISSUES} issues x {INDEXERS} indexers in {elapsed:.1f}s "
          f"({sum(len(t) for t in fake.arrivals.values())} requests; slow indexer alone needs ~{slowest:.0f}s)")  # fmt: skip
    assert elapsed < slowest * 1.5
