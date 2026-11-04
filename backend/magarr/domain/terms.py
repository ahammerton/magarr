"""Release-name terms for profile rules: plain case-insensitive text, or /regex/."""

from __future__ import annotations

import re


def term_matches(term: str, text: str) -> bool:
    term = term.strip()
    if len(term) > 2 and term.startswith("/") and term.endswith("/"):
        try:
            return re.search(term[1:-1], text, re.IGNORECASE) is not None
        except re.error:
            return False  # invalid patterns are rejected when the profile is saved
    return term.casefold() in text.casefold()


def validate_terms(terms: list[str]) -> list[str]:
    """Clean a term list; raise ValueError for an invalid /regex/."""
    cleaned: list[str] = []
    for term in terms:
        term = term.strip()
        if not term:
            continue
        if len(term) > 2 and term.startswith("/") and term.endswith("/"):
            try:
                re.compile(term[1:-1])
            except re.error as exc:
                raise ValueError(f"Invalid regular expression {term}: {exc}") from exc
        if term not in cleaned:
            cleaned.append(term)
    return cleaned
