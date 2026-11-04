"""Phase 7 performance: no N+1 queries, indexes where queries look, paging on lists."""

import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event


@contextmanager
def count_queries(api: TestClient):
    counter = {"n": 0}

    def before(*_):
        counter["n"] += 1

    engine = api.app.state.engine
    event.listen(engine, "before_cursor_execute", before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _settle(api: TestClient) -> None:
    """Let background work (notification deliveries) finish so it isn't counted."""
    queue = api.app.state.notifications.queue
    deadline = time.monotonic() + 5
    while not queue.empty() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)


def _add_magazines(api: TestClient, library_dir: Path, first: int, last: int) -> list[dict]:
    """Magazines ``first``..``last - 1``, each with 4 issues (2 with files, 1 downloading, with
    history) and a stray file in the root folder."""
    from magarr.domain.enums import HistoryEventType
    from magarr.domain.history import record
    from magarr.domain.models import Download, Issue

    made = []
    for n in range(first, last):
        mag = api.post(
            "/api/v1/magazine", json={"title": f"Mag {n}", "frequency": "monthly"}
        ).json()
        for month in range(1, 5):
            api.post(
                "/api/v1/issue",
                json={"magazineId": mag["id"], "issueNumber": f"2024-{month:02d}",
                      "publishDate": f"2024-{month:02d}-01", "monitored": month > 2},
            )  # fmt: skip
        folder = library_dir / mag["folder"]
        folder.mkdir(parents=True)
        for month in (1, 2):
            (folder / f"Mag {n} 2024-{month:02d}.pdf").write_bytes(b"pdf")
        (library_dir / f"loose {n}.pdf").write_bytes(b"x")  # unmapped
        made.append(mag)
    api.post("/api/v1/library/scan", json={})
    ids = [m["id"] for m in made]
    with api.app.state.session_factory() as session:
        for issue in session.query(Issue).filter(
            Issue.issue_number == "2024-03", Issue.magazine_id.in_(ids)
        ):
            session.add(Download(issue_id=issue.id, external_id=f"x{issue.id}", title="t",
                                 protocol="usenet", status="downloading"))  # fmt: skip
            record(session, HistoryEventType.GRABBED, "t", issue, client="SAB", source="RSS sync")
        session.commit()
    _settle(api)
    return made


ENDPOINTS = [
    "/api/v1/magazine",
    "/api/v1/issue?magazineId={id}",
    "/api/v1/wanted?pageSize=500",
    "/api/v1/calendar?start=2024-01-01&end=2024-12-31",
    "/api/v1/history?pageSize=500",
    "/api/v1/queue",
    "/api/v1/library/unmapped",
    "/api/v1/blocklist",
]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_list_endpoints_dont_query_per_row(
    api: TestClient, root_folder: dict, library_dir: Path, endpoint: str
) -> None:
    url = endpoint.format(id=_add_magazines(api, library_dir, 0, 2)[0]["id"])
    with count_queries(api) as few:
        assert api.get(url).status_code == 200
    _add_magazines(api, library_dir, 2, 20)  # ten times the library
    with count_queries(api) as many:
        assert api.get(url).status_code == 200
    assert many["n"] == few["n"], (
        f"{endpoint}: {few['n']} queries for 2 magazines, {many['n']} for 20"
    )


# --- Indexes -----------------------------------------------------------------------------------


def test_every_foreign_key_is_indexed() -> None:
    from magarr.core.db import Base

    missing = []
    for table in Base.metadata.sorted_tables:
        leading = {next(c.name for c in index.columns) for index in table.indexes}
        leading |= {
            constraint.columns.keys()[0]
            for constraint in table.constraints
            if constraint.__class__.__name__ in ("UniqueConstraint", "PrimaryKeyConstraint")
            and constraint.columns
        }
        for fk in table.foreign_keys:
            if fk.parent.name not in leading:
                missing.append(f"{table.name}.{fk.parent.name}")
    assert missing == []


def _plan(api: TestClient, sql: str) -> str:
    from sqlalchemy import text

    with api.app.state.engine.connect() as conn:
        return " | ".join(row[-1] for row in conn.execute(text(f"EXPLAIN QUERY PLAN {sql}")))


def _sql(statement) -> str:
    from sqlalchemy.dialects import sqlite

    return str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))


def _backlog_sql() -> str:
    from datetime import UTC, datetime

    from magarr.pipeline.automation import backlog_query

    return _sql(backlog_query(datetime(2026, 11, 2, tzinfo=UTC), 10))


@pytest.mark.parametrize(
    ("name", "sql"),
    [
        (
            "wanted",
            "SELECT issues.id FROM issues JOIN magazines ON issues.magazine_id = magazines.id "
            "WHERE issues.status = 'missing' ORDER BY issues.publish_date DESC, magazines.sort_title LIMIT 50",
        ),
        (
            "calendar",
            "SELECT id FROM issues WHERE publish_date >= '2026-10-01' AND publish_date <= '2026-11-30'",
        ),
        ("issues of a magazine", "SELECT id FROM issues WHERE magazine_id = 1 ORDER BY sort_index"),
        ("history of an issue", "SELECT id FROM history WHERE issue_id = 1 ORDER BY id DESC"),
        ("queue", "SELECT id FROM downloads WHERE status IN ('queued', 'downloading')"),
        ("magazine list", "SELECT id FROM magazines ORDER BY sort_title"),
        (
            "task history",
            "SELECT id FROM task_runs WHERE name = 'rss' ORDER BY started_at DESC LIMIT 50",
        ),
    ],
)
def test_busy_queries_use_an_index(api: TestClient, name: str, sql: str | None) -> None:
    plan = _plan(api, sql)
    steps = [step.strip() for step in plan.split("|")]
    full_scans = [s for s in steps if s.startswith("SCAN ") and "INDEX" not in s]
    assert full_scans == [], f"{name} scans a whole table: {plan}"
    # Sorting only ties ("RIGHT PART") is fine; sorting every row is not.
    assert "USE TEMP B-TREE FOR ORDER BY" not in plan, f"{name} sorts every row: {plan}"


def test_the_history_page_walks_the_primary_key(api: TestClient) -> None:
    plan = _plan(api, "SELECT id FROM history ORDER BY id DESC LIMIT 50")
    assert plan == "SCAN history" and "TEMP B-TREE" not in plan  # newest 50 rows, then stops


def test_the_backlog_query_finds_wanted_issues_by_index(api: TestClient) -> None:
    """It filters through a (status, ...) index; sorting the wanted subset that leaves is fine
    (timed below on a big library)."""
    plan = _plan(api, _backlog_sql())
    assert "SEARCH issues USING INDEX ix_issues_status_" in plan, plan
    assert not [s for s in plan.split(" | ") if s.startswith("SCAN ")], plan


def test_a_big_library_stays_fast(api: TestClient, root_folder: dict) -> None:
    """20,000 issues across 400 magazines, 5,000 of them wanted."""
    from datetime import UTC, date, datetime

    from sqlalchemy import insert

    from magarr.domain.models import Issue, Magazine
    from magarr.pipeline.automation import backlog_candidates

    with api.app.state.session_factory() as session:
        profile_id = session.scalar(select_profile_id())
        session.execute(
            insert(Magazine),
            [
                {"title": f"M{n}", "sort_title": f"m{n:04d}", "folder": f"M{n}", "language": "en",
                 "frequency": "monthly", "quality_profile_id": profile_id,
                 "root_folder_id": root_folder["id"], "monitored": True,
                 "alternate_titles": [], "tags": [], "grab_new_specials": False}
                for n in range(400)
            ],
        )  # fmt: skip
        ids = [m.id for m in session.query(Magazine.id)]
        rows = []
        for magazine_id in ids:
            for k in range(50):
                year, month = 2020 + k // 12, k % 12 + 1
                wanted = k >= 37 or k % 10 == 0
                rows.append({
                    "magazine_id": magazine_id, "issue_number": f"{year}-{month:02d}",
                    "sort_index": float(year * 10000 + month * 100), "publish_date": date(year, month, 1),
                    "monitored": wanted, "status": "wanted" if wanted else "missing",
                })  # fmt: skip
        session.execute(insert(Issue), rows)
        session.commit()
        assert session.query(Issue).count() == 20_000

        started = time.perf_counter()
        found = backlog_candidates(session, datetime(2026, 11, 2, tzinfo=UTC), 10)
        backlog_ms = (time.perf_counter() - started) * 1000
    assert len(found) == 10
    timings = {"backlog query": backlog_ms}
    for url in [
        "/api/v1/magazine",
        "/api/v1/wanted?pageSize=50",
        "/api/v1/calendar?start=2024-01-01&end=2024-03-31",
        f"/api/v1/issue?magazineId={ids[0]}",
    ]:
        started = time.perf_counter()
        assert api.get(url).status_code == 200
        timings[url] = (time.perf_counter() - started) * 1000
    print({k: round(v) for k, v in timings.items()})  # shown with pytest -s
    slow = {k: round(v) for k, v in timings.items() if v > 500}
    assert slow == {}, f"slow on a big library (ms): {slow}"


def select_profile_id():
    from sqlalchemy import select

    from magarr.domain.models import QualityProfile

    return select(QualityProfile.id).limit(1)


# --- Paging ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/magazine",
        "/api/v1/issue?magazineId={id}",
        "/api/v1/queue",
        "/api/v1/library/unmapped",
        "/api/v1/blocklist",
    ],
)
def test_list_endpoints_page_on_request(
    api: TestClient, root_folder: dict, library_dir: Path, endpoint: str
) -> None:
    from magarr.domain.models import BlocklistItem

    made = _add_magazines(api, library_dir, 0, 6)
    with api.app.state.session_factory() as session:
        session.add_all(
            BlocklistItem(guid=f"g{n}", source_title=f"t{n}", protocol="usenet") for n in range(6)
        )
        session.commit()
    url = endpoint.format(id=made[0]["id"])
    whole = api.get(url)
    total = int(whole.headers["X-Total-Count"])
    assert total == len(whole.json()) >= 4  # no paging asked for: everything
    sep = "&" if "?" in url else "?"
    first = api.get(f"{url}{sep}page=1&pageSize=3")
    second = api.get(f"{url}{sep}page=2&pageSize=3")
    assert first.headers["X-Total-Count"] == str(total)
    assert len(first.json()) == 3
    assert first.json() + second.json() == whole.json()[:6]
    assert api.get(f"{url}{sep}pageSize=5000").status_code == 422  # at most 1000
