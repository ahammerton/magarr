from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.domain.models import Indexer, Issue, Magazine
from magarr.pipeline.search import build_queries, evaluate
from tests.indexer_fakes import NZB_URL, TORZNAB_URL, newznab_router, torznab_router


def _indexer(api: TestClient, name: str, url: str, impl: str = "newznab", **extra) -> dict:
    base, path = url.rsplit("/", 1)
    body = {
        "name": name,
        "implementation": impl,
        "baseUrl": base,
        "apiPath": path,
        "apiKey": "K",
        "requestInterval": 0,
        **extra,
    }
    response = api.post("/api/v1/indexer", json=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def issue(api: TestClient, magazine: dict) -> dict:
    api.patch(f"/api/v1/magazine/{magazine['id']}", json={"alternateTitles": ["Nat Geo"]})
    body = {
        "magazineId": magazine["id"],
        "issueNumber": "2025-01",
        "publishDate": "2025-01-01",
        "monitored": True,
    }
    return api.post("/api/v1/issue", json=body).json()


@respx.mock
def test_search_across_indexers(api: TestClient, issue: dict) -> None:
    nzb = respx.get(NZB_URL).mock(side_effect=newznab_router)
    respx.get(TORZNAB_URL).mock(side_effect=torznab_router)
    _indexer(api, "Usenet", NZB_URL, priority=10)
    _indexer(api, "Torrents", TORZNAB_URL, impl="torznab")

    result = api.post(f"/api/v1/issue/{issue['id']}/search").json()

    assert result["queries"] == ["National Geographic 2025", "Nat Geo 2025"]
    assert [(o["name"], o["ok"], o["releaseCount"]) for o in result["indexers"]] == [
        ("Usenet", True, 3),  # deduplicated across the two queries
        ("Torrents", True, 3),
    ]
    assert {c.request.url.params["q"] for c in nzb.calls} == {
        "National Geographic 2025",
        "Nat Geo 2025",
    }

    releases = {r["title"]: r for r in result["releases"]}
    approved = [r["title"] for r in result["releases"] if not r["rejected"]]
    # Approved first, ranked by the profile: PDF (Hi-Res) beats PDF, then newer beats older.
    assert approved == [
        "National Geographic UK - January 2025 (HQ PDF)",
        "National.Geographic.USA.2025.01.HYBRID.MAGAZiNE.eBook-PDF",
        "National.Geographic.UK.2025.01.True.PDF",
    ]
    hq = releases["National Geographic UK - January 2025 (HQ PDF)"]
    assert hq["parsed"] == {
        "magazineTitle": "National Geographic UK",
        "issueNumber": "2025-01",
        "year": 2025,
        "month": 1,
        "format": "pdf",
        "quality": "pdf_hires",
        "edition": "UK",
        "group": None,
        "isPack": False,
        "language": None,
    }
    assert (hq["seeders"], hq["leechers"], hq["protocol"], hq["indexer"]) == (
        42,
        8,
        "torrent",
        "Torrents",
    )
    assert hq["ageDays"] >= 0
    # Download links carry the indexer's API key, so they are never sent to the browser.
    assert all("downloadUrl" not in r for r in result["releases"])
    assert "r=KEY" not in str(result)  # the fixture's NZB link embeds the key as r=KEY

    reasons = {t: r["rejectionReasons"] for t, r in releases.items() if r["rejected"]}
    assert reasons == {
        "National Geographic - February 2025": ["Wrong issue: release is 2025-02"],
        "National Geographic Complete Year 2024": [
            "Multi-issue pack (grab it manually to import every issue in it)"
        ],
        "National Geographic Traveller UK - January 2025": [
            "Different magazine: 'National Geographic Traveller UK'"
        ],
    }


@respx.mock
def test_tagged_and_disabled_indexers_are_skipped(api: TestClient, issue: dict) -> None:
    tagged = respx.get(TORZNAB_URL).mock(side_effect=torznab_router)
    respx.get(NZB_URL).mock(side_effect=newznab_router)
    _indexer(api, "Tech only", TORZNAB_URL, impl="torznab", tags=["tech"])
    _indexer(api, "Off", "https://off.example/api", enabled=False)
    backed_off = _indexer(api, "Resting", "https://rest.example/api")
    _indexer(api, "Usenet", NZB_URL)

    session = api.app.state.session_factory()
    row = session.get(Indexer, backed_off["id"])
    row.disabled_until = datetime.now(UTC) + timedelta(minutes=10)
    row.last_error = "Timed out"
    session.commit()
    session.close()

    result = api.post(f"/api/v1/issue/{issue['id']}/search").json()
    outcomes = {o["name"]: o for o in result["indexers"]}
    assert set(outcomes) == {"Resting", "Usenet"}
    assert outcomes["Resting"]["ok"] is False
    assert outcomes["Resting"]["skippedUntil"] is not None
    assert outcomes["Resting"]["error"] == "Timed out"
    assert tagged.call_count == 0

    # Tag the magazine and the tagged indexer applies.
    api.patch(f"/api/v1/magazine/{issue['magazineId']}", json={"tags": ["Tech"]})
    result = api.post(f"/api/v1/issue/{issue['id']}/search").json()
    assert "Tech only" in {o["name"] for o in result["indexers"]}


@respx.mock
def test_failing_indexer_does_not_break_search(api: TestClient, issue: dict) -> None:
    healthy = respx.get(NZB_URL).mock(side_effect=newznab_router)
    broken = respx.get("https://down.example/api").mock(side_effect=httpx.ConnectError("refused"))
    down = _indexer(api, "Down", "https://down.example/api")
    _indexer(api, "Usenet", NZB_URL)

    for _ in range(3):
        result = api.post(f"/api/v1/issue/{issue['id']}/search").json()
        assert len(result["releases"]) == 3
        outcome = next(o for o in result["indexers"] if o["name"] == "Down")
        assert outcome["ok"] is False
        assert "Could not reach" in outcome["error"]

    # Repeat searches hit the cache for the healthy indexer; the broken one is retried
    # (1 query each time; the first failure aborts its remaining queries).
    assert healthy.call_count == 2 * 2  # 2 queries x 2 pages, once
    assert broken.call_count == 3

    status = api.get(f"/api/v1/indexer/{down['id']}").json()
    assert status["consecutiveFailures"] == 3
    assert status["disabledUntil"] is not None  # threshold reached: backed off


def test_search_with_no_indexers(api: TestClient, issue: dict) -> None:
    result = api.post(f"/api/v1/issue/{issue['id']}/search").json()
    assert result["releases"] == [] and result["indexers"] == []


def test_search_unknown_issue(api: TestClient) -> None:
    assert api.post("/api/v1/issue/999/search").status_code == 404


# --- Unit level -------------------------------------------------------------------------------


def _mag(**kw) -> Magazine:
    return Magazine(
        title=kw.pop("title", "Wired"),
        alternate_titles=kw.pop("alts", []),
        tags=[],
        folder="x",
        **kw,
    )


def test_queries_for_numbered_issue() -> None:
    magazine = _mag(title="Edge", alts=["Edge Magazine", "EDGE", "Edge UK"])
    issue = Issue(issue_number="395", publish_date=date(2024, 4, 1))
    # Number and year queries, case-insensitive dedupe, at most three titles.
    assert build_queries(magazine, issue) == [
        "Edge 395",
        "Edge 2024",
        "Edge Magazine 395",
        "Edge Magazine 2024",
    ]


def test_queries_without_date_or_number() -> None:
    assert build_queries(_mag(), Issue(issue_number="Summer Special")) == ["Wired"]


def _release(title: str):
    from magarr.domain.enums import Protocol
    from magarr.indexers.client import IndexerRelease

    return IndexerRelease(
        guid=title, title=title, download_url="x", info_url=None, size=1, publish_date=None,
        categories=(), seeders=None, leechers=None, grabs=None, indexer_id=1, indexer="i",
        protocol=Protocol.USENET,
    )  # fmt: skip


def test_edition_mismatch_only_when_magazine_names_a_region() -> None:
    issue = Issue(issue_number="2024-05", publish_date=date(2024, 5, 1))
    uk = _mag(title="Wired UK")
    assert evaluate(_release("Wired.UK.2024.05.PDF"), uk, issue).approved
    assert evaluate(_release("Wired.USA.2024.05.PDF"), uk, issue).rejections == [
        "Different magazine: 'Wired USA'"
    ]
    # Same title family, different region spelled out: an edition mismatch.
    ng = _mag(title="National Geographic UK", alts=["National Geographic"])
    assert evaluate(_release("National.Geographic.US.2024.05"), ng, issue).rejections == [
        "Different edition: US"
    ]
    # No region in the magazine's titles: any edition is accepted.
    plain = _mag(title="National Geographic")
    assert evaluate(_release("National.Geographic.US.2024.05"), plain, issue).approved


def test_unparseable_release() -> None:
    issue = Issue(issue_number="1")
    result = evaluate(_release("Wired"), _mag(), issue)
    assert result.rejections == ["Could not determine the issue from the release name"]


def test_language_editions_are_rejected() -> None:
    """Real NZBgeek naming: scene language tags mark foreign editions."""
    issue = Issue(issue_number="594", publish_date=date(2026, 9, 1))
    english = _mag(title="National Geographic", language="en")
    spanish = _release("National.Geographic.No.594.2026.SPANiSH.HYBRiD.MAGAZiNE")
    assert evaluate(spanish, english, issue).rejections == [
        "Different language: Spanish (magazine is 'en')"
    ]
    # A Spanish-language magazine accepts it; untagged releases count as English.
    assert evaluate(spanish, _mag(title="National Geographic", language="es"), issue).approved
    assert evaluate(_release("National.Geographic.No.594.2026"), english, issue).approved


def test_different_magazine_skips_issue_checks() -> None:
    issue = Issue(issue_number="2026-06", publish_date=date(2026, 6, 1))
    result = evaluate(
        _release("National.Geographic.Little.Kids.No.46.2026.HYBRiD.MAGAZiNE"),
        _mag(title="National Geographic"),
        issue,
    )
    assert result.rejections == ["Different magazine: 'National Geographic Little Kids'"]
