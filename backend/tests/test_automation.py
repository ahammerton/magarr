"""Phase 5: RSS sync, backlog search, expected issues, retries, wanted list and calendar."""

from datetime import UTC, date, datetime, timedelta
from xml.sax.saxutils import escape

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.domain.expected import next_issues, roll_expected_issues
from magarr.domain.models import HistoryEvent, Issue, Magazine
from magarr.pipeline.automation import Automation, backlog_search, rss_sync
from magarr.pipeline.tracking import poll_once
from tests.download_fakes import SAB_KEY, SAB_URL, FakeSab
from tests.indexer_fakes import NZB_URL, fixture, xml

TODAY = date(2026, 10, 21)


def feed(*titles: str) -> bytes:
    items = "".join(
        f"""<item><title>{escape(t)}</title><guid>https://nzb.example/details/{i}</guid>
        <link>https://nzb.example/getnzb/{i}.nzb</link>
        <pubDate>Wed, 21 Oct 2026 08:00:00 +0000</pubDate>
        <enclosure url="https://nzb.example/getnzb/{i}.nzb" length="40000000"
          type="application/x-nzb"/>
        <newznab:attr name="category" value="7010"/><newznab:attr name="size" value="40000000"/>
        </item>"""
        for i, t in enumerate(titles)
    )
    return (
        '<?xml version="1.0"?><rss version="2.0" '
        'xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"><channel>'
        f'<newznab:response offset="0" total="{len(titles)}"/>{items}</channel></rss>'
    ).encode()


class FakeIndexer:
    """Newznab: the RSS feed (no q) and searches (q) serve what the test puts in them."""

    def __init__(self) -> None:
        self.rss: list[str] = []
        self.search: dict[str, list[str]] = {}
        self.requests: list[httpx.QueryParams] = []
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        self.requests.append(params)
        if params.get("t") == "caps":
            return xml("newznab_caps.xml")
        if self.down:
            return httpx.Response(503)
        if "q" not in params:
            return httpx.Response(200, content=feed(*self.rss))
        query = params["q"].casefold()
        titles = [t for q, ts in self.search.items() if q.casefold() in query for t in ts]
        return httpx.Response(200, content=feed(*titles))

    @property
    def searches(self) -> list[str]:
        return [p["q"] for p in self.requests if "q" in p]

    @property
    def rss_requests(self) -> int:
        return sum(1 for p in self.requests if p.get("t") == "search" and "q" not in p)


@pytest.fixture
def indexer() -> FakeIndexer:
    return FakeIndexer()


@pytest.fixture
def sab() -> FakeSab:
    return FakeSab()


@pytest.fixture
def env(api: TestClient, magazine: dict, indexer: FakeIndexer, sab: FakeSab):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(NZB_URL).mock(side_effect=indexer)
        mock.get(url__startswith="https://nzb.example/getnzb/").mock(
            return_value=httpx.Response(200, content=fixture("sample.nzb"))
        )
        mock.route(url__startswith=SAB_URL).mock(side_effect=sab)
        api.post(
            "/api/v1/indexer",
            json={"name": "Usenet", "baseUrl": "https://nzb.example", "apiKey": "K",
                  "requestInterval": 0},
        )  # fmt: skip
        api.post(
            "/api/v1/downloadclient",
            json={"name": "SAB", "implementation": "sabnzbd",
                  "settings": {"host": "sab.local", "apiKey": SAB_KEY}},
        )  # fmt: skip
        yield {"magazine": magazine, "mock": mock}


def _issue(api: TestClient, magazine: dict, number: str, monitored: bool = True, **extra) -> dict:
    body = {"magazineId": magazine["id"], "issueNumber": number, "monitored": monitored, **extra}
    if "publishDate" not in extra and len(number) == 7:
        body["publishDate"] = f"{number}-01"
    response = api.post("/api/v1/issue", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _run(api: TestClient, job):
    async def go():
        with api.app.state.session_factory() as session:
            return await job(session, api.app.state.indexer_runtime)

    return api.portal.call(go)


def _sources(api: TestClient) -> list[tuple[str, str]]:
    with api.app.state.session_factory() as session:
        rows = session.query(HistoryEvent).filter_by(event_type="grabbed").order_by(HistoryEvent.id)
        return [(h.source_title, h.data["source"]) for h in rows]


# --- Expected issues ---------------------------------------------------------------------------


def _magazine(frequency: str, numbers: list[tuple[str, date]], monitored=True) -> Magazine:
    magazine = Magazine(title="M", folder="M", frequency=frequency, monitored=monitored)
    magazine.issues = [Issue(issue_number=n, publish_date=d, monitored=False) for n, d in numbers]
    return magazine


def test_monthly_schedule_rolls_forward_in_the_same_style() -> None:
    m = _magazine("monthly", [("2026-08", date(2026, 8, 1)), ("2026-09", date(2026, 9, 1))])
    # 45 days ahead of 21 October reaches 5 December: the December issue may come out early.
    assert next_issues(m, TODAY, 45) == [
        ("2026-10", date(2026, 10, 1)),
        ("2026-11", date(2026, 11, 1)),
        ("2026-12", date(2026, 12, 1)),
    ]
    assert [n for n, _ in next_issues(m, TODAY, 0)] == ["2026-10"]


def test_numbered_weekly_issues_continue_the_numbering() -> None:
    m = _magazine("weekly", [("1589", date(2026, 10, 9))])
    assert next_issues(m, TODAY, 7) == [("1590", date(2026, 10, 16)), ("1591", date(2026, 10, 23))]


@pytest.mark.parametrize(
    ("frequency", "latest", "expected"),
    [
        ("weekly", ("2026-W41", date(2026, 10, 5)), ["2026-W42", "2026-W43", "2026-W44"]),
        ("quarterly", ("2026-Q3", date(2026, 7, 1)), ["2026-Q4"]),
        ("weekly", ("2026-10-10", date(2026, 10, 10)), ["2026-10-17", "2026-10-24"]),
    ],
)
def test_other_numbering_styles(frequency: str, latest: tuple, expected: list[str]) -> None:
    assert [n for n, _ in next_issues(_magazine(frequency, [latest]), TODAY, 7)] == expected


def test_a_magazine_that_stopped_long_ago_gets_nothing() -> None:
    # e.g. ACE, monitored, last issue 1992: don't invent issue 465 for this autumn.
    assert next_issues(_magazine("monthly", [("55", date(1992, 6, 1))]), TODAY, 45) == []
    assert next_issues(_magazine("monthly", [("1992-06", date(1992, 6, 1))]), TODAY, 45) == []


def test_a_few_missed_issues_only_fill_the_last_two_periods() -> None:
    m = _magazine("monthly", [("2026-05", date(2026, 5, 1))])  # five months ago: still active
    assert [n for n, _ in next_issues(m, TODAY, 45)] == ["2026-09", "2026-10", "2026-11", "2026-12"]
    numbered = _magazine("monthly", [("400", date(2026, 5, 1))])
    assert [n for n, _ in next_issues(numbered, TODAY, 0)] == ["404", "405"]  # Sep, Oct


@pytest.mark.parametrize(
    "numbers",
    [
        [("Vol 3 No 2", date(2026, 9, 1))],  # can't guess what comes next
        [("Special 2026", date(2026, 9, 1))],
        [("2026-09", None)],  # no dates at all
    ],
)
def test_no_guessing_without_a_regular_numbered_issue(numbers) -> None:
    assert next_issues(_magazine("monthly", numbers), TODAY, 45) == []


def test_a_special_does_not_derail_the_schedule() -> None:
    m = _magazine(
        "monthly",
        [("2026-09", date(2026, 9, 1)), ("Christmas Special 2026", date(2026, 12, 1))],
    )
    assert [n for n, _ in next_issues(m, TODAY, 45)] == ["2026-10", "2026-11", "2026-12"]


def test_ad_hoc_magazines_are_not_rolled() -> None:
    assert next_issues(_magazine("ad-hoc", [("2026-09", date(2026, 9, 1))]), TODAY, 45) == []


def test_roll_creates_wanted_issues_for_monitored_magazines_only(
    api: TestClient, magazine: dict
) -> None:
    _issue(api, magazine, "2026-09", monitored=False)
    other = api.post("/api/v1/magazine", json={"title": "Wired", "monitored": False}).json()
    _issue(api, other, "2026-09")
    with api.app.state.session_factory() as session:
        result = roll_expected_issues(session, TODAY, 45)
        session.commit()
        assert result.magazines == ["National Geographic"]
        again = roll_expected_issues(session, TODAY, 45)
        assert again.created == []  # idempotent
    issues = {
        i["issueNumber"]: i for i in api.get(f"/api/v1/issue?magazineId={magazine['id']}").json()
    }
    assert issues["2026-10"]["status"] == "wanted"
    assert issues["2026-11"]["publishDate"] == "2026-11-01"
    assert issues["2026-09"]["status"] == "missing"  # existing issues are left alone


# --- RSS sync ----------------------------------------------------------------------------------


def test_rss_grabs_a_new_release_for_a_wanted_issue(api: TestClient, env, indexer, sab) -> None:
    wanted = _issue(api, env["magazine"], "2026-11")
    indexer.rss = [
        "Wired.2026.11.PDF",  # another magazine
        "National.Geographic.2026.10.PDF",  # no such issue
        "National.Geographic.November.2026.PDF",
    ]
    result = _run(api, rss_sync)
    assert result.grabbed == ["National.Geographic.November.2026.PDF"]
    assert _sources(api) == [("National.Geographic.November.2026.PDF", "RSS sync")]
    assert sab.added[0]["cat"] == "magazines"
    assert api.get(f"/api/v1/issue/{wanted['id']}").json()["download"]["status"] == "queued"
    assert indexer.searches == []  # the feed was enough

    # Already-seen releases aren't evaluated (or grabbed) again.
    again = _run(api, rss_sync)
    assert (again.new, again.grabbed) == (0, [])


def test_rss_picks_the_best_release_per_issue(api: TestClient, env, indexer) -> None:
    _issue(api, env["magazine"], "2026-11")
    indexer.rss = ["National.Geographic.2026.11.EPUB", "National.Geographic.2026.11.HQ.PDF"]
    assert _run(api, rss_sync).grabbed == ["National.Geographic.2026.11.HQ.PDF"]


@pytest.mark.parametrize(
    "case", ["unmonitored issue", "unmonitored magazine", "before cutoff", "has file"]
)
def test_rss_ignores_issues_that_are_not_wanted(
    api: TestClient, env, indexer, case: str, library_dir
) -> None:
    magazine = env["magazine"]
    _issue(api, magazine, "2026-11", monitored=case != "unmonitored issue")
    _issue(api, magazine, "2026-12")  # keeps RSS running: something is wanted
    if case == "unmonitored magazine":
        api.patch(f"/api/v1/magazine/{magazine['id']}", json={"monitored": False})
    if case == "before cutoff":
        api.patch(f"/api/v1/magazine/{magazine['id']}", json={"searchCutoff": "2026-12-01"})
    if case == "has file":
        folder = library_dir / magazine["folder"]
        folder.mkdir(parents=True)
        (folder / "National Geographic - 2026-11.pdf").write_bytes(b"x")
        api.post("/api/v1/library/scan", json={})
    indexer.rss = ["National.Geographic.2026.11.PDF"]
    assert _run(api, rss_sync).grabbed == []


def test_rss_does_not_call_indexers_when_nothing_is_wanted(api: TestClient, env, indexer) -> None:
    _issue(api, env["magazine"], "2026-11", monitored=False)
    _run(api, rss_sync)
    assert indexer.rss_requests == 0


def test_rss_falls_back_to_title_searches_when_the_feed_is_empty(
    api: TestClient, env, indexer
) -> None:
    _issue(api, env["magazine"], "2026-11")
    indexer.search = {"National Geographic": ["National.Geographic.2026.11.PDF"]}
    assert _run(api, rss_sync).grabbed == ["National.Geographic.2026.11.PDF"]
    assert indexer.searches == ["National Geographic"]


def test_rss_records_indexer_failures(api: TestClient, env, indexer) -> None:
    _issue(api, env["magazine"], "2026-11")
    indexer.down = True
    result = _run(api, rss_sync)
    assert "Usenet" in result.errors
    [row] = api.get("/api/v1/indexer").json()
    assert row["lastError"]


# --- Backlog search ----------------------------------------------------------------------------


def _backlog(api: TestClient, batch: int, now: datetime | None = None):
    return _run(api, lambda s, r: backlog_search(s, r, batch, now))


def test_backlog_searches_oldest_first_in_batches_and_resumes(
    api: TestClient, env, indexer
) -> None:
    magazine = env["magazine"]
    for number in ("2024-03", "2024-01", "2024-02", "2024-04"):
        _issue(api, magazine, number)
    _issue(api, magazine, "2027-06")  # not out yet: not searched
    _issue(api, magazine, "2023-12", monitored=False)  # not wanted

    first = _backlog(api, 2)
    assert first.searched == 2
    # Both issues send the same query; the second answer comes from the cache.
    assert indexer.searches == ["National Geographic 2024"]
    searched = {
        i["issueNumber"]
        for i in api.get(f"/api/v1/issue?magazineId={magazine['id']}").json()
        if i["lastSearchedAt"]
    }
    assert searched == {"2024-01", "2024-02"}

    # The next batch carries on, then nothing is due until a day has passed.
    assert _backlog(api, 2).searched == 2
    assert _backlog(api, 2).searched == 0
    later = datetime.now(UTC) + timedelta(hours=25)
    assert _backlog(api, 10, later).searched == 4


def test_backlog_grabs_and_stops_per_issue(api: TestClient, env, indexer) -> None:
    issue = _issue(api, env["magazine"], "2024-01")
    indexer.search = {"National Geographic 2024": ["National.Geographic.2024.01.PDF"]}
    result = _backlog(api, 10)
    assert result.grabbed == ["National.Geographic.2024.01.PDF"]
    assert _sources(api) == [("National.Geographic.2024.01.PDF", "backlog search")]
    assert api.get(f"/api/v1/issue/{issue['id']}").json()["download"] is not None


def test_backlog_respects_the_magazine_cutoff(api: TestClient, env, indexer) -> None:
    magazine = env["magazine"]
    _issue(api, magazine, "2009-12")
    _issue(api, magazine, "2010-01")
    api.patch(f"/api/v1/magazine/{magazine['id']}", json={"searchCutoff": "2010-01-01"})
    assert _backlog(api, 10).searched == 1
    assert indexer.searches == ["National Geographic 2010"]


def test_backlog_leaves_the_cursor_when_indexers_are_down(api: TestClient, env, indexer) -> None:
    _issue(api, env["magazine"], "2024-01")
    indexer.down = True
    result = _backlog(api, 10)
    assert (result.searched, result.stopped) == (0, "No indexer answered")
    [issue] = api.get(f"/api/v1/issue?magazineId={env['magazine']['id']}").json()
    assert issue["lastSearchedAt"] is None


# --- Failed downloads: retry limit -------------------------------------------------------------


def test_retries_stop_after_the_limit(api: TestClient, env, indexer, sab) -> None:
    issue = _issue(api, env["magazine"], "2024-01")
    api.put("/api/v1/config/downloads", json={"redownloadFailed": True, "maxRetries": 1})
    indexer.search = {
        "National Geographic 2024": [
            "National.Geographic.2024.01.HQ.PDF",
            "National.Geographic.2024.01.PDF",
            "National.Geographic.2024.01.True.PDF",
        ]
    }
    _backlog(api, 1)
    poll = lambda: _run(api, poll_once)  # noqa: E731

    sab.fail(sab.added[-1]["nzo_id"], "CRC error")
    assert poll().retried == [issue["id"]]  # first failure: one retry allowed
    sab.fail(sab.added[-1]["nzo_id"], "CRC error")
    assert poll().retried == []  # second failure: over the limit
    assert len(sab.added) == 2


# --- Scheduler ---------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_scheduler_runs_jobs_on_their_intervals(api: TestClient, env, indexer) -> None:
    _issue(api, env["magazine"], "2026-09")
    clock = Clock()
    automation = Automation(
        api.app.state.session_factory, api.app.state.indexer_runtime, clock=clock
    )
    api.portal.call(automation.tick)
    assert set(automation.status) == {"expected", "rss", "backlog"}
    assert indexer.rss_requests == 1

    clock.now = 14 * 60  # RSS every 15 minutes by default
    api.portal.call(automation.tick)
    assert indexer.rss_requests == 1
    clock.now = 15 * 60
    api.portal.call(automation.tick)
    assert indexer.rss_requests == 2
    assert automation.status["rss"].last_result.endswith("grabbed")


def test_global_monitoring_switch_pauses_everything(api: TestClient, env, indexer) -> None:
    _issue(api, env["magazine"], "2026-09")
    settings = api.get("/api/v1/config/automation").json()
    api.put("/api/v1/config/automation", json={**settings, "monitoringEnabled": False})
    automation = Automation(api.app.state.session_factory, api.app.state.indexer_runtime)
    api.portal.call(automation.tick)
    assert automation.status == {} and indexer.requests == []


# --- API ---------------------------------------------------------------------------------------


def test_automation_settings_round_trip_and_limits(api: TestClient) -> None:
    settings = api.get("/api/v1/config/automation").json()
    assert settings == {
        "monitoringEnabled": True,
        "rssIntervalMinutes": 15,
        "backlogIntervalMinutes": 60,
        "backlogBatchSize": 10,
        "expectedLookaheadDays": 45,
        "jobs": [
            {"name": "expected", "lastRun": None, "lastResult": None},
            {"name": "rss", "lastRun": None, "lastResult": None},
            {"name": "backlog", "lastRun": None, "lastResult": None},
        ],
    }
    body = {k: v for k, v in settings.items() if k != "jobs"}
    saved = api.put("/api/v1/config/automation", json={**body, "rssIntervalMinutes": 0})
    assert saved.json()["rssIntervalMinutes"] == 0  # 0 turns it off
    too_fast = api.put("/api/v1/config/automation", json={**body, "rssIntervalMinutes": 5})
    assert too_fast.status_code == 400
    assert "10 minutes" in too_fast.json()["message"]


def test_wanted_list_filters_and_pages(api: TestClient, magazine: dict) -> None:
    for number in ("2024-01", "2024-02", "2024-03"):
        _issue(api, magazine, number)
    _issue(api, magazine, "2023-01", monitored=False)
    other = api.post("/api/v1/magazine", json={"title": "Wired"}).json()
    _issue(api, other, "2024-05")

    page = api.get("/api/v1/wanted?pageSize=2").json()
    assert page["total"] == 4
    assert [(r["magazineTitle"], r["issueNumber"]) for r in page["records"]] == [
        ("Wired", "2024-05"),
        ("National Geographic", "2024-03"),
    ]
    mine = api.get(f"/api/v1/wanted?magazineId={magazine['id']}&page=2&pageSize=2").json()
    assert [r["issueNumber"] for r in mine["records"]] == ["2024-01"]
    missing = api.get("/api/v1/wanted?status=missing").json()
    assert [r["issueNumber"] for r in missing["records"]] == ["2023-01"]


def test_wanted_search_runs_in_the_background(api: TestClient, env, indexer) -> None:
    issue = _issue(api, env["magazine"], "2024-01")
    indexer.search = {"National Geographic 2024": ["National.Geographic.2024.01.PDF"]}
    response = api.post("/api/v1/wanted/search", json={"issueIds": [issue["id"]]})
    assert (response.status_code, response.json()) == (202, {"queued": 1})

    async def wait():
        await api.app.state.automation._drain()  # finish (or join) the queued work

    api.portal.call(wait)
    assert _sources(api) == [("National.Geographic.2024.01.PDF", "wanted search")]


def test_calendar_shows_monitored_magazines_in_range(api: TestClient, magazine: dict) -> None:
    _issue(api, magazine, "2026-10")
    _issue(api, magazine, "2026-11", monitored=False)
    _issue(api, magazine, "2027-01")
    quiet = api.post("/api/v1/magazine", json={"title": "Wired", "monitored": False}).json()
    _issue(api, quiet, "2026-10")

    days = api.get("/api/v1/calendar?start=2026-10-01&end=2026-11-30").json()
    assert [(d["magazineTitle"], d["issueNumber"], d["status"]) for d in days] == [
        ("National Geographic", "2026-10", "wanted"),
        ("National Geographic", "2026-11", "missing"),
    ]
    everything = api.get("/api/v1/calendar?start=2026-10-01&end=2026-10-31&unmonitored=true")
    assert len(everything.json()) == 2
    assert api.get("/api/v1/calendar?start=2026-10-02&end=2026-10-01").status_code == 400
    assert api.get("/api/v1/calendar?start=2020-01-01&end=2026-01-01").status_code == 400


def test_search_cutoff_round_trips(api: TestClient, magazine: dict) -> None:
    assert magazine["searchCutoff"] is None
    saved = api.patch(f"/api/v1/magazine/{magazine['id']}", json={"searchCutoff": "2010-01-01"})
    assert saved.json()["searchCutoff"] == "2010-01-01"
    cleared = api.patch(f"/api/v1/magazine/{magazine['id']}", json={"searchCutoff": None})
    assert cleared.json()["searchCutoff"] is None


@pytest.mark.parametrize("enabled", [False, True])
def test_rss_adds_new_specials_only_when_the_magazine_asks(
    api: TestClient, env, indexer, enabled: bool
) -> None:
    magazine = env["magazine"]
    _issue(api, magazine, "2026-11")  # something wanted, so RSS runs
    api.patch(f"/api/v1/magazine/{magazine['id']}", json={"grabNewSpecials": enabled})
    indexer.rss = ["National.Geographic.Christmas.Special.2026.PDF"]
    result = _run(api, rss_sync)
    numbers = {
        i["issueNumber"]: i for i in api.get(f"/api/v1/issue?magazineId={magazine['id']}").json()
    }
    if not enabled:
        assert result.grabbed == [] and "Christmas Special 2026" not in numbers
        return
    assert result.grabbed == ["National.Geographic.Christmas.Special.2026.PDF"]
    special = numbers["Christmas Special 2026"]
    assert (special["monitored"], special["publishDate"]) == (True, "2026-12-01")
    assert special["download"] is not None


def test_rss_does_not_add_a_special_for_a_rejected_release(api: TestClient, env, indexer) -> None:
    magazine = env["magazine"]
    _issue(api, magazine, "2026-11")
    api.patch(f"/api/v1/magazine/{magazine['id']}", json={"grabNewSpecials": True})
    indexer.rss = ["National.Geographic.Christmas.Special.2026.GERMAN.PDF"]  # wrong language
    assert _run(api, rss_sync).grabbed == []
    numbers = {
        i["issueNumber"] for i in api.get(f"/api/v1/issue?magazineId={magazine['id']}").json()
    }
    assert "Christmas Special 2026" not in numbers


def test_grab_new_specials_round_trips(api: TestClient, magazine: dict) -> None:
    assert magazine["grabNewSpecials"] is False
    saved = api.patch(f"/api/v1/magazine/{magazine['id']}", json={"grabNewSpecials": True})
    assert saved.json()["grabNewSpecials"] is True
