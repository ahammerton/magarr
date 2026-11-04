"""Match parsed names to known magazines (fuzzy) and issues (exact keys or dates)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from rapidfuzz import fuzz, process

from magarr.domain.models import Issue, Magazine
from magarr.importers.parsing import ParsedIssue

# Minimum rapidfuzz score (0-100) for a fuzzy title match.
TITLE_MATCH_THRESHOLD = 90

_YEAR_SUFFIX = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")


def normalize_title(title: str) -> str:
    text = _YEAR_SUFFIX.sub("", title).casefold().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"^the\s+", "", text.strip())
    return re.sub(r"\s+", " ", text).strip()


def normalize_issue_number(value: str) -> str:
    text = re.sub(r"[^\w]", "", value.casefold())
    return re.sub(r"(?<!\d)0+(?=\d)", "", text)


def match_magazine(name: str, magazines: Iterable[Magazine]) -> Magazine | None:
    """Best magazine for a folder or title: exact normalized match, then fuzzy."""
    target = normalize_title(name)
    if not target:
        return None
    candidates: dict[str, Magazine] = {}
    for magazine in magazines:
        for title in (magazine.title, magazine.folder, *(magazine.alternate_titles or [])):
            candidates.setdefault(normalize_title(title), magazine)
    if target in candidates:
        return candidates[target]
    best = process.extractOne(
        target, candidates.keys(), scorer=fuzz.token_sort_ratio, score_cutoff=TITLE_MATCH_THRESHOLD
    )
    return candidates[best[0]] if best else None


# Words that don't name a special: "2313 BBC Good Food UK" is just "Special 2023".
_NOT_A_SPECIAL_NAME = {"special", "issue", "edition", "the", "magazine", "mag", "uk", "us", "usa"}


def specialise[P: ParsedIssue](parsed: P, magazine: Magazine) -> P:
    """Name a "month 13" special from what the file adds to the magazine's title:
    "2513 Fine Scale Modeler Ship Handbook" -> "Ship Handbook 2025"; otherwise "Special 2025"
    (or "Christmas Special 2024", already set by the parser)."""
    if not parsed.thirteenth or parsed.special != "Special":
        return parsed
    titles = [magazine.title, magazine.folder, *(magazine.alternate_titles or [])]
    known = {word for title in titles for word in normalize_title(title).split()}
    words = [
        w
        for w in re.findall(r"[^\W_]+(?:'[^\W_]+)?", parsed.title)
        if w.casefold() not in known and w.casefold() not in _NOT_A_SPECIAL_NAME
    ]
    if not words:
        return parsed
    name = " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words)
    return replace(parsed, special=name)


def match_issue(parsed: ParsedIssue, issues: Iterable[Issue]) -> Issue | None:
    issues = list(issues)
    key = parsed.issue_key
    if key:
        wanted = normalize_issue_number(key)
        for issue in issues:
            if normalize_issue_number(issue.issue_number) == wanted:
                return issue

    # Fall back to the publish date when the file only tells us when it came out.
    if parsed.number or parsed.special or not parsed.year:
        return None
    when = parsed.publish_date
    if when is None:
        return None
    if parsed.day or parsed.week:
        candidates = [i for i in issues if i.publish_date == when]
    elif parsed.month or parsed.quarter:
        candidates = [
            i
            for i in issues
            if i.publish_date
            and i.publish_date.year == when.year
            and i.publish_date.month == when.month
        ]
    else:
        return None
    return candidates[0] if len(candidates) == 1 else None
