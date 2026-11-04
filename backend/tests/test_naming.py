"""Golden-file style tests for naming pattern rendering (§3.3, §8)."""

from datetime import date

import pytest

from magarr.domain.errors import DomainError
from magarr.domain.naming import (
    IssueNamingInput,
    NamingScheme,
    find_collisions,
    issue_relative_path,
    magazine_folder_name,
    sanitize,
    validate_scheme,
)

SCHEME = NamingScheme(year_folder_pattern="Season {year}")  # the brief's §3.3 layout


def _issue(**overrides: object) -> IssueNamingInput:
    values: dict = {
        "magazine_title": "Magazine Title",
        "issue_number": "045",
        "first_issue_year": 1999,
        "publish_date": date(2014, 7, 1),
        "format": "pdf",
    }
    return IssueNamingInput(**{**values, **overrides})


def test_brief_example_path() -> None:
    folder = magazine_folder_name("Magazine Title", 1999, None, SCHEME)
    assert f"{folder}/{issue_relative_path(_issue(), SCHEME)}" == (
        "Magazine Title (1999)/Season 2014/Magazine Title - 2014-07 - Issue 045.pdf"
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"publish_date": None}, "Magazine Title - Issue 045.pdf"),
        ({"format": None}, "Season 2014/Magazine Title - 2014-07 - Issue 045"),
        ({"magazine_title": "AC/DC: Live?"}, "Season 2014/AC-DC - Live - 2014-07 - Issue 045.pdf"),
        ({"format": "EPUB"}, "Season 2014/Magazine Title - 2014-07 - Issue 045.epub"),
    ],
)
def test_issue_paths(overrides: dict, expected: str) -> None:
    assert str(issue_relative_path(_issue(**overrides), SCHEME)) == expected


def test_folder_without_year_drops_empty_brackets() -> None:
    assert magazine_folder_name("Wired", None, None, SCHEME) == "Wired"


def test_default_is_flat_no_year_folders() -> None:
    """Default: everything directly in the magazine folder (readers like Komga see one series)."""
    assert NamingScheme().year_folder_pattern == ""
    assert (
        str(issue_relative_path(_issue(), NamingScheme()))
        == "Magazine Title - 2014-07 - Issue 045.pdf"
    )


def test_year_folder_is_optional() -> None:
    years = NamingScheme(year_folder_pattern="{year}")
    assert (
        str(issue_relative_path(_issue(), years)) == "2014/Magazine Title - 2014-07 - Issue 045.pdf"
    )


def test_per_magazine_template_overrides_pattern() -> None:
    path = issue_relative_path(_issue(), SCHEME, template="{issue_number} {issue_title}")
    assert str(path) == "Season 2014/045.pdf"


def test_remove_instead_of_replace() -> None:
    scheme = NamingScheme(replace_illegal_characters=False, colon_replacement="")
    assert sanitize('A/B: "C"?', scheme) == "AB C"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("issue_file_pattern", "{magazine_title}", "must include {issue_number}"),
        ("issue_file_pattern", "{issue_number} {bogus}", "unknown token"),
        ("issue_file_pattern", "{issue_number}/x", "path separators"),
        ("issue_file_pattern", "{issue_number} {year", "malformed"),
        ("magazine_folder_pattern", "{year}", "unknown token"),
        ("magazine_folder_pattern", "", "cannot be empty"),
        ("year_folder_pattern", "{month}", "unknown token"),
        ("colon_replacement", ":", "illegal"),
    ],
)
def test_invalid_schemes(field: str, value: str, message: str) -> None:
    scheme = NamingScheme(**{field: value})
    with pytest.raises(DomainError, match=message):
        validate_scheme(scheme)


def test_collisions_are_case_insensitive() -> None:
    from pathlib import PurePosixPath

    paths = {1: PurePosixPath("A/x.pdf"), 2: PurePosixPath("a/X.pdf"), 3: PurePosixPath("b.pdf")}
    assert find_collisions(paths) == [(1, 2, "a/X.pdf")]
