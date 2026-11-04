"""Folder and file naming patterns (§3.3).

Patterns use ``{token}`` placeholders. Tokens with no value render empty, and the leftover
separators/brackets are tidied up, so ``{magazine_title} ({first_issue_year})`` renders
``Wired`` when the year is unknown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from magarr.domain.errors import DomainError

MAGAZINE_FOLDER_TOKENS = frozenset({"magazine_title", "first_issue_year", "publisher"})
YEAR_FOLDER_TOKENS = frozenset({"year"})
ISSUE_FILE_TOKENS = frozenset(
    {
        "magazine_title",
        "first_issue_year",
        "publisher",
        "issue_number",
        "issue_title",
        "year",
        "month",
        "day",
        "publish_date",
        "format",
        "quality",
    }
)

DEFAULT_MAGAZINE_FOLDER_PATTERN = "{magazine_title} ({first_issue_year})"
# Blank: every issue sits directly in the magazine folder. Readers such as Komga treat each
# folder as a series, so year sub-folders would show up as separate series named "2026".
DEFAULT_YEAR_FOLDER_PATTERN = ""
DEFAULT_ISSUE_FILE_PATTERN = "{magazine_title} - {year}-{month} - Issue {issue_number}"

_TOKEN = re.compile(r"\{([a-z_]+)\}")
_ILLEGAL_REPLACEMENTS = {
    "/": "-",
    "\\": "-",
    "*": "-",
    "|": "-",
    '"': "'",
    "<": "",
    ">": "",
    "?": "",
}


@dataclass(frozen=True)
class NamingScheme:
    magazine_folder_pattern: str = DEFAULT_MAGAZINE_FOLDER_PATTERN
    year_folder_pattern: str = DEFAULT_YEAR_FOLDER_PATTERN
    issue_file_pattern: str = DEFAULT_ISSUE_FILE_PATTERN
    replace_illegal_characters: bool = True
    colon_replacement: str = " -"


def pattern_tokens(pattern: str) -> set[str]:
    return set(_TOKEN.findall(pattern))


def validate_pattern(
    pattern: str, allowed: frozenset[str], required: set[str], label: str, allow_empty: bool = False
) -> None:
    if not pattern.strip():
        if allow_empty:
            return
        raise DomainError(f"{label} cannot be empty")
    if "/" in pattern or "\\" in pattern:
        raise DomainError(f"{label} cannot contain path separators")
    if pattern.count("{") != pattern.count("}") or _TOKEN.sub("", pattern).count("{"):
        raise DomainError(f"{label} has an unmatched or malformed {{token}}")
    tokens = pattern_tokens(pattern)
    if unknown := tokens - allowed:
        raise DomainError(f"{label} uses unknown token(s): {', '.join(sorted(unknown))}")
    if missing := required - tokens:
        names = ", ".join(f"{{{t}}}" for t in sorted(missing))
        raise DomainError(f"{label} must include {names}")


def validate_issue_pattern(pattern: str, label: str = "Issue file pattern") -> None:
    # issue_number is unique per magazine, so requiring it keeps file names unique.
    validate_pattern(pattern, ISSUE_FILE_TOKENS, {"issue_number"}, label)


def validate_scheme(scheme: NamingScheme) -> None:
    validate_pattern(
        scheme.magazine_folder_pattern,
        MAGAZINE_FOLDER_TOKENS,
        {"magazine_title"},
        "Magazine folder pattern",
    )
    validate_pattern(
        scheme.year_folder_pattern,
        YEAR_FOLDER_TOKENS,
        set(),
        "Year folder pattern",
        allow_empty=True,
    )
    validate_issue_pattern(scheme.issue_file_pattern)
    if any(ch in scheme.colon_replacement for ch in '/\\:*?"<>|'):
        raise DomainError("Colon replacement cannot contain illegal characters")


def sanitize(name: str, scheme: NamingScheme) -> str:
    name = name.replace(":", scheme.colon_replacement)
    for char, replacement in _ILLEGAL_REPLACEMENTS.items():
        name = name.replace(char, replacement if scheme.replace_illegal_characters else "")
    name = re.sub(r"[\x00-\x1f]", "", name)
    # Windows disallows trailing dots/spaces.
    return re.sub(r"\s+", " ", name).strip().rstrip(". ")


def _tidy(text: str) -> str:
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\s*-\s*){2,}", " - ", text)  # "A -  - B" -> "A - B"
    return text.strip(" -_.")


def render(pattern: str, values: dict[str, str | None], scheme: NamingScheme) -> str:
    def substitute(match: re.Match[str]) -> str:
        value = values.get(match[1])
        return sanitize(value, scheme) if value else ""

    return sanitize(_tidy(_TOKEN.sub(substitute, pattern)), scheme)


def magazine_folder_name(
    title: str, first_issue_year: int | None, publisher: str | None, scheme: NamingScheme
) -> str:
    values = {
        "magazine_title": title,
        "first_issue_year": str(first_issue_year) if first_issue_year else None,
        "publisher": publisher,
    }
    return render(scheme.magazine_folder_pattern, values, scheme)


@dataclass(frozen=True)
class IssueNamingInput:
    magazine_title: str
    issue_number: str
    first_issue_year: int | None = None
    publisher: str | None = None
    issue_title: str | None = None
    publish_date: date | None = None
    format: str | None = None
    quality: str | None = None


def issue_relative_path(
    issue: IssueNamingInput, scheme: NamingScheme, template: str | None = None
) -> PurePosixPath:
    """Path of an issue file relative to its magazine folder (extension included)."""
    when = issue.publish_date
    values = {
        "magazine_title": issue.magazine_title,
        "first_issue_year": str(issue.first_issue_year) if issue.first_issue_year else None,
        "publisher": issue.publisher,
        "issue_number": issue.issue_number,
        "issue_title": issue.issue_title,
        "year": str(when.year) if when else None,
        "month": f"{when.month:02d}" if when else None,
        "day": f"{when.day:02d}" if when else None,
        "publish_date": when.isoformat() if when else None,
        "format": issue.format.upper() if issue.format else None,
        "quality": issue.quality,
    }
    file_name = render(template or scheme.issue_file_pattern, values, scheme)
    if issue.format:
        file_name = f"{file_name}.{issue.format.lower()}"
    year_folder = render(scheme.year_folder_pattern, values, scheme) if when else ""
    return PurePosixPath(year_folder, file_name) if year_folder else PurePosixPath(file_name)


def find_collisions(paths: dict[int, PurePosixPath]) -> list[tuple[int, int, str]]:
    """Pairs of ids whose paths collide on a case-insensitive filesystem."""
    seen: dict[str, int] = {}
    collisions: list[tuple[int, int, str]] = []
    for entity_id, path in paths.items():
        key = str(path).casefold()
        if key in seen:
            collisions.append((seen[key], entity_id, str(path)))
        else:
            seen[key] = entity_id
    return collisions
