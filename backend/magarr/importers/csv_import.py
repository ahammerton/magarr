"""Bulk issue import from CSV (§4.1): rows of magazine title, issue number, publish date."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from magarr.domain.errors import DomainError
from magarr.domain.issues import compute_sort_index, resolve_status
from magarr.domain.magazines import MagazineFields, create_magazine, find_by_title
from magarr.domain.models import Issue, Magazine
from magarr.domain.naming_config import check_magazine_collisions, get_scheme

MAX_ROWS = 20_000

_COLUMNS = {
    "magazine": ("magazine", "magazine_title", "title"),
    "issue": ("issue", "issue_number", "number"),
    "date": ("date", "publish_date", "published"),
    "issue_title": ("issue_title", "name"),
}


@dataclass
class RowError:
    row: int
    message: str


@dataclass
class CsvImportResult:
    issues_created: int = 0
    issues_updated: int = 0
    issues_unchanged: int = 0
    magazines_created: list[str] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    # ISO only: DD/MM vs MM/DD is ambiguous and would silently corrupt dates.
    if len(raw) == 7:
        raw = f"{raw}-01"
    if len(raw) == 4 and raw.isdigit():
        raw = f"{raw}-01-01"
    return date.fromisoformat(raw)


def _header_map(fieldnames: list[str]) -> dict[str, str]:
    normalized = {name.strip().lower().replace(" ", "_"): name for name in fieldnames}
    mapping: dict[str, str] = {}
    for key, aliases in _COLUMNS.items():
        for alias in aliases:
            if alias in normalized:
                mapping[key] = normalized[alias]
                break
    if "magazine" not in mapping or "issue" not in mapping:
        raise DomainError("CSV needs a header row with 'magazine' and 'issue' columns")
    return mapping


def import_csv(
    session: Session, text: str, create_missing: bool, monitored: bool
) -> CsvImportResult:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise DomainError("CSV is empty")
    columns = _header_map(list(reader.fieldnames))
    result = CsvImportResult()
    magazines: dict[str, Magazine | None] = {}
    touched: set[int] = set()

    for line_no, row in enumerate(reader, start=2):
        if line_no - 1 > MAX_ROWS:
            raise DomainError(f"CSV has more than {MAX_ROWS} rows")

        def cell(key: str, row: dict[str, str | None] = row) -> str:
            column = columns.get(key)
            return (row.get(column) or "").strip() if column else ""

        title, number = cell("magazine"), cell("issue")
        if not title and not number:
            continue
        if not title or not number:
            result.errors.append(RowError(line_no, "Magazine and issue are required"))
            continue
        try:
            when = _parse_date(cell("date"))
        except ValueError:
            result.errors.append(
                RowError(line_no, f"Invalid date '{cell('date')}' (use YYYY-MM-DD)")
            )
            continue

        key = title.casefold()
        if key not in magazines:
            magazines[key] = find_by_title(session, title)
            if magazines[key] is None and create_missing:
                try:
                    magazines[key] = create_magazine(session, MagazineFields(title=title))
                except DomainError as exc:
                    result.errors.append(RowError(line_no, exc.message))
                    continue
                result.magazines_created.append(title)
        magazine = magazines[key]
        if magazine is None:
            result.errors.append(RowError(line_no, f"Unknown magazine '{title}'"))
            continue

        issue_title = cell("issue_title") or None
        existing = next(
            (i for i in magazine.issues if i.issue_number.casefold() == number.casefold()), None
        )
        if existing is None:
            issue = Issue(
                issue_number=number,
                title=issue_title,
                publish_date=when,
                sort_index=compute_sort_index(number, when),
                monitored=monitored,
            )
            resolve_status(issue)
            magazine.issues.append(issue)
            result.issues_created += 1
        else:
            changed = False
            if when and existing.publish_date != when:
                existing.publish_date = when
                changed = True
            if issue_title and existing.title != issue_title:
                existing.title = issue_title
                changed = True
            if changed:
                result.issues_updated += 1
            else:
                result.issues_unchanged += 1
        touched.add(magazine.id)

    scheme = get_scheme(session)
    for magazine in {m.id: m for m in magazines.values() if m}.values():
        if magazine.id in touched:
            check_magazine_collisions(magazine, scheme)
    session.flush()
    return result
