from datetime import UTC, datetime, timedelta

import pytest

from magarr.domain.enums import Protocol
from magarr.domain.models import Issue, IssueFile, QualityProfile, QualityProfileItem
from magarr.domain.terms import term_matches, validate_terms
from magarr.indexers.client import IndexerRelease
from magarr.pipeline.decision import DecisionContext, profile_rejections, rank_key

ORDER = ["pdf_hires", "pdf", "epub", "unknown"]


def _profile(**overrides) -> QualityProfile:
    items = [
        QualityProfileItem(
            quality=q,
            allowed=q != "unknown",
            max_size_mb=100 if q == "pdf" else None,
            upgrade_until=q == "pdf",
            position=i,
        )
        for i, q in enumerate(ORDER)
    ]
    rules = {
        "protocols": ["usenet", "torrent"],
        "must_contain": [],
        "must_not_contain": [],
        **overrides,
    }
    return QualityProfile(name="Test", items=items, **rules)


def _release(
    title="Wired.2024.05.PDF", size=50, protocol=Protocol.USENET, seeders=None, age_days=1
) -> IndexerRelease:
    return IndexerRelease(
        guid=title, title=title, download_url="x", info_url=None, size=size * 1024 * 1024,
        publish_date=datetime.now(UTC) - timedelta(days=age_days), categories=(), seeders=seeders,
        leechers=None, grabs=None, indexer_id=1, indexer="i", protocol=protocol,
    )  # fmt: skip


def _ctx(profile=None, file_quality=None, **kw) -> DecisionContext:
    issue = Issue(issue_number="2024-05")
    issue.file = (
        IssueFile(relative_path="a.pdf", size=1, format="pdf", quality=file_quality)
        if file_quality
        else None
    )
    return DecisionContext(profile=profile or _profile(), issue=issue, **kw)


def test_clean_release_is_approved() -> None:
    assert profile_rejections(_release(), "pdf", _ctx()) == []


def test_quality_not_allowed_and_size_cap() -> None:
    assert profile_rejections(_release(), "unknown", _ctx()) == [
        "Quality Unknown is not allowed by profile 'Test'"
    ]
    assert profile_rejections(_release(), "cbz", _ctx()) == [
        "Quality CBZ is not allowed by profile 'Test'"
    ]
    assert profile_rejections(_release(size=150), "pdf", _ctx()) == [
        "Size 150 MB is over the 100 MB limit for PDF"
    ]
    assert profile_rejections(_release(size=150), "epub", _ctx()) == []  # no cap for EPUB


def test_protocol_rule() -> None:
    ctx = _ctx(_profile(protocols=["usenet"]))
    assert profile_rejections(_release(protocol=Protocol.TORRENT), "pdf", ctx) == [
        "Protocol torrent is not allowed by the profile"
    ]


def test_must_and_must_not_contain() -> None:
    ctx = _ctx(
        _profile(must_contain=["True PDF", "/\\bHQ\\b/"], must_not_contain=["SPANiSH", "/sample/"])
    )
    assert profile_rejections(_release("Wired.2024.05.True.PDF"), "pdf", ctx) == [
        "Does not contain any of: True PDF, /\\bHQ\\b/"
    ]
    assert profile_rejections(_release("Wired 2024 05 true pdf"), "pdf", ctx) == []
    assert profile_rejections(_release("Wired.2024.05.HQ.PDF"), "pdf", ctx) == []
    assert profile_rejections(_release("Wired 2024 05 HQ spanish"), "pdf", ctx) == [
        "Contains a forbidden term: SPANiSH"
    ]


def test_blocklist_and_active_download() -> None:
    release = _release()
    assert profile_rejections(release, "pdf", _ctx(blocked_guids={(1, release.guid)})) == [
        "Blocklisted after an earlier failed download"
    ]
    assert profile_rejections(release, "pdf", _ctx(blocked_titles={release.title.casefold()})) == [
        "Blocklisted after an earlier failed download"
    ]
    assert profile_rejections(release, "pdf", _ctx(has_active_download=True)) == [
        "This issue already has a download in progress"
    ]


@pytest.mark.parametrize(
    ("have", "candidate", "expected"),
    [
        ("epub", "pdf_hires", []),  # upgrade
        ("epub", "epub", ["Not an upgrade over the existing EPUB file"]),
        (
            "epub",
            "unknown",
            [
                "Quality Unknown is not allowed by profile 'Test'",
                "Not an upgrade over the existing EPUB file",
            ],
        ),
        ("pdf", "pdf_hires", ["Existing file (PDF) meets the upgrade cutoff"]),
        ("pdf_hires", "pdf_hires", ["Existing file (PDF (Hi-Res)) meets the upgrade cutoff"]),
    ],
)
def test_upgrades(have: str, candidate: str, expected: list[str]) -> None:
    assert profile_rejections(_release(), candidate, _ctx(file_quality=have)) == expected


def test_ranking_quality_then_seeders_then_age_then_priority() -> None:
    ctx = _ctx()
    keys = {
        "hires": rank_key(_release(age_days=9), "pdf_hires", ctx, 25),
        "pdf_new": rank_key(_release(age_days=1), "pdf", ctx, 25),
        "pdf_old": rank_key(_release(age_days=5), "pdf", ctx, 25),
        "pdf_seeded": rank_key(
            _release(age_days=7, seeders=50, protocol=Protocol.TORRENT), "pdf", ctx, 25
        ),
        "pdf_new_low_prio": rank_key(_release(age_days=1), "pdf", ctx, 40),
        "epub": rank_key(_release(age_days=0), "epub", ctx, 1),
    }
    assert sorted(keys, key=keys.get) == [
        "hires",
        "pdf_seeded",
        "pdf_new",
        "pdf_new_low_prio",
        "pdf_old",
        "epub",
    ]


def test_terms() -> None:
    assert term_matches("true pdf", "Wired.True PDF") and not term_matches("x", "y")
    assert term_matches("/^wired/", "WIRED.2024")
    assert validate_terms([" a ", "", "a", "/b+/"]) == ["a", "/b+/"]
    with pytest.raises(ValueError, match="Invalid regular expression"):
        validate_terms(["/(unclosed/"])
