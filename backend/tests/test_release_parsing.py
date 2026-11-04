"""Release-title parser corpus (tests/corpus/releases.tsv)."""

from pathlib import Path

import pytest

from magarr.importers.parsing import parse_release

CORPUS = Path(__file__).parent / "corpus" / "releases.tsv"


def _rows() -> list[pytest.param]:
    rows = []
    for line_no, line in enumerate(CORPUS.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        cells += [""] * (10 - len(cells))
        source, title, *expected = cells[:10]
        marks = (
            [pytest.mark.xfail(strict=True, reason="known parser gap")] if source == "gap" else []
        )
        rows.append(pytest.param(title, expected, id=f"{line_no}:{source}:{title}", marks=marks))
    return rows


@pytest.mark.parametrize(("title", "expected"), _rows())
def test_release_corpus(title: str, expected: list[str]) -> None:
    magazine, key, published, fmt, quality, edition, pack, language = expected
    parsed = parse_release(title)
    actual = [
        parsed.title,
        parsed.issue_key or "",
        parsed.publish_date.isoformat() if parsed.publish_date else "",
        parsed.format.value if parsed.format else "",
        parsed.quality if parsed.format else "",
        parsed.edition or "",
        "yes" if parsed.is_pack else "no",
        parsed.language or "",
    ]
    assert actual == [magazine, key, published, fmt, quality, edition, pack, language]


def test_corpus_counts() -> None:
    """The brief asks for >=200 real release names."""
    sources = [p.id.split(":")[1] for p in _rows()]
    assert sources.count("real") >= 200
    assert set(sources) <= {"hand", "real", "gap"}


def test_group_suffix_and_leaked_extension() -> None:
    parsed = parse_release("Retro.Gamer.Issue.260.2024.HQ.PDF-SCENE.pdf")
    assert (parsed.group, parsed.issue_key, parsed.quality) == ("SCENE", "260", "pdf_hires")
    # "...eBook-PDF" is a format, not a release group.
    assert parse_release("Wired.USA.May.2024.HYBRID.MAGAZiNE.eBook-PDF").group is None
