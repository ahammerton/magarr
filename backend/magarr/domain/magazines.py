from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from magarr.domain.enums import Frequency, IssueStatus
from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.issues import compute_sort_index, expected_issue_slots, resolve_status
from magarr.domain.models import Issue, IssueFile, Magazine, QualityProfile, RootFolder
from magarr.domain.naming import magazine_folder_name, validate_issue_pattern
from magarr.domain.naming_config import check_magazine_collisions, get_scheme
from magarr.domain.profiles import default_profile_id
from magarr.domain.root_folders import default_root_folder_id

_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def sort_title(title: str) -> str:
    return _ARTICLES.sub("", title.strip()).casefold()


def _clean_list(values: list[str] | None) -> list[str]:
    seen: dict[str, str] = {}
    for value in values or []:
        value = value.strip()
        if value and value.casefold() not in seen:
            seen[value.casefold()] = value
    return list(seen.values())


@dataclass
class MagazineFields:
    """Writable magazine fields. On update, only names in ``provided`` are applied."""

    title: str | None = None
    alternate_titles: list[str] | None = None
    publisher: str | None = None
    language: str | None = None
    category: str | None = None
    frequency: Frequency | None = None
    first_issue_year: int | None = None
    tags: list[str] | None = None
    quality_profile_id: int | None = None
    root_folder_id: int | None = None
    folder: str | None = None
    monitored: bool | None = None
    poster_url: str | None = None
    search_cutoff: date | None = None
    grab_new_specials: bool | None = None
    issue_naming_template: str | None = None
    notes: str | None = None
    provided: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class MagazineStats:
    issue_count: int = 0
    downloaded_count: int = 0
    wanted_count: int = 0
    size_on_disk: int = 0


def get_magazine(session: Session, magazine_id: int) -> Magazine:
    magazine = session.get(Magazine, magazine_id)
    if magazine is None:
        raise NotFoundError(f"Magazine {magazine_id} not found")
    return magazine


def find_by_title(session: Session, title: str) -> Magazine | None:
    """Case-insensitive match on title or any alternate title."""
    wanted = title.strip().casefold()
    match = session.scalar(select(Magazine).where(func.lower(Magazine.title) == wanted))
    if match:
        return match
    for magazine in session.scalars(select(Magazine)):
        if any(alt.casefold() == wanted for alt in magazine.alternate_titles or []):
            return magazine
    return None


def _check_title(session: Session, title: str, exclude_id: int | None = None) -> str:
    title = title.strip()
    if not title:
        raise DomainError("Title cannot be empty")
    existing = find_by_title(session, title)
    if existing and existing.id != exclude_id:
        raise ConflictError(f"'{title}' already exists as '{existing.title}'")
    return title


def _check_refs(session: Session, root_folder_id: int | None, profile_id: int | None) -> None:
    if root_folder_id is not None and session.get(RootFolder, root_folder_id) is None:
        raise DomainError(f"Root folder {root_folder_id} does not exist")
    if profile_id is not None and session.get(QualityProfile, profile_id) is None:
        raise DomainError(f"Quality profile {profile_id} does not exist")


def _check_folder(
    session: Session, root_folder_id: int, folder: str, exclude_id: int | None = None
) -> str:
    folder = folder.strip()
    if not folder or folder in (".", "..") or "/" in folder or "\\" in folder:
        raise DomainError("Folder must be a single directory name")
    stmt = select(Magazine.title).where(
        Magazine.root_folder_id == root_folder_id, Magazine.folder == folder
    )
    if exclude_id is not None:
        stmt = stmt.where(Magazine.id != exclude_id)
    if (other := session.scalar(stmt)) is not None:
        raise ConflictError(f"Folder '{folder}' is already used by '{other}'")
    return folder


def create_magazine(session: Session, fields: MagazineFields) -> Magazine:
    title = _check_title(session, fields.title or "")
    root_id = fields.root_folder_id or default_root_folder_id(session)
    profile_id = fields.quality_profile_id or default_profile_id(session)
    if root_id is None:
        raise DomainError("Add a root folder before adding magazines")
    if profile_id is None:
        raise DomainError("Add a quality profile before adding magazines")
    _check_refs(session, root_id, profile_id)
    if fields.issue_naming_template:
        validate_issue_pattern(fields.issue_naming_template, "Issue naming template")

    scheme = get_scheme(session)
    folder = fields.folder or magazine_folder_name(
        title, fields.first_issue_year, fields.publisher, scheme
    )
    magazine = Magazine(
        title=title,
        sort_title=sort_title(title),
        alternate_titles=_clean_list(fields.alternate_titles),
        publisher=fields.publisher,
        language=fields.language or "en",
        category=fields.category,
        frequency=(fields.frequency or Frequency.MONTHLY).value,
        first_issue_year=fields.first_issue_year,
        tags=_clean_list(fields.tags),
        quality_profile_id=profile_id,
        root_folder_id=root_id,
        folder=_check_folder(session, root_id, folder),
        monitored=True if fields.monitored is None else fields.monitored,
        poster_url=fields.poster_url,
        search_cutoff=fields.search_cutoff,
        grab_new_specials=bool(fields.grab_new_specials),
        issue_naming_template=fields.issue_naming_template or None,
        notes=fields.notes,
    )
    session.add(magazine)
    session.flush()
    return magazine


def update_magazine(session: Session, magazine_id: int, fields: MagazineFields) -> Magazine:
    magazine = get_magazine(session, magazine_id)
    values: dict[str, Any] = {name: getattr(fields, name) for name in fields.provided}

    if "title" in values:
        values["title"] = _check_title(session, values["title"] or "", exclude_id=magazine.id)
        values["sort_title"] = sort_title(values["title"])
    for name in ("alternate_titles", "tags"):
        if name in values:
            values[name] = _clean_list(values[name])
    for name in (
        "quality_profile_id",
        "root_folder_id",
        "frequency",
        "language",
        "monitored",
        "grab_new_specials",
    ):
        if name in values and values[name] is None:
            raise DomainError(f"{name} cannot be null")
    if "frequency" in values:
        values["frequency"] = values["frequency"].value
    _check_refs(session, values.get("root_folder_id"), values.get("quality_profile_id"))
    if "root_folder_id" in values or "folder" in values:
        values["folder"] = _check_folder(
            session,
            values.get("root_folder_id", magazine.root_folder_id),
            values.get("folder") or magazine.folder,
            exclude_id=magazine.id,
        )
    if "issue_naming_template" in values:
        template = values["issue_naming_template"] or None
        if template:
            validate_issue_pattern(template, "Issue naming template")
        check_magazine_collisions(magazine, get_scheme(session), template or "")
        values["issue_naming_template"] = template

    for name, value in values.items():
        setattr(magazine, name, value)
    session.flush()
    session.refresh(magazine, ["root_folder"])
    return magazine


def delete_magazine(session: Session, magazine_id: int) -> None:
    """Removes the magazine and its issue records. Files on disk are left alone."""
    session.delete(get_magazine(session, magazine_id))
    session.flush()


def magazine_stats(
    session: Session, magazine_ids: list[int] | None = None
) -> dict[int, MagazineStats]:
    """Per-magazine counts in one query (no N+1)."""
    stmt = (
        select(
            Issue.magazine_id,
            func.count(Issue.id),
            func.sum(case((Issue.status == IssueStatus.DOWNLOADED.value, 1), else_=0)),
            func.sum(case((Issue.status == IssueStatus.WANTED.value, 1), else_=0)),
            func.coalesce(func.sum(IssueFile.size), 0),
        )
        .outerjoin(IssueFile, IssueFile.issue_id == Issue.id)
        .group_by(Issue.magazine_id)
    )
    if magazine_ids is not None:
        stmt = stmt.where(Issue.magazine_id.in_(magazine_ids))
    return {
        row[0]: MagazineStats(int(row[1]), int(row[2] or 0), int(row[3] or 0), int(row[4] or 0))
        for row in session.execute(stmt)
    }


@dataclass(frozen=True)
class GenerateResult:
    created: list[Issue]
    skipped: int


def generate_issues(
    session: Session,
    magazine_id: int,
    start: date | None,
    count: int,
    monitored: bool,
    first_number: int | None = None,
) -> GenerateResult:
    """Create expected issues. Existing issue numbers (and, with dates, existing dates) are skipped.

    Date numbering ("2026-09") needs a schedule and a start date. Issue numbering ("360", "361")
    works for any frequency; with a schedule and a start date each issue also gets its expected
    publish date, otherwise issues have no date (e.g. ad-hoc magazines).
    """
    magazine = get_magazine(session, magazine_id)
    if not 1 <= count <= 520:
        raise DomainError("Count must be between 1 and 520")
    frequency = Frequency(magazine.frequency)
    scheduled = frequency is not Frequency.AD_HOC

    if first_number is None:
        if not scheduled:
            raise DomainError(
                "Ad-hoc magazines have no schedule to generate dated issues from; "
                "number them instead (e.g. starting at issue 1)"
            )
        if start is None:
            raise DomainError("A first issue date is needed to generate issues by date")
        slots: list[tuple[str, date | None]] = list(expected_issue_slots(frequency, start, count))
    else:
        if first_number < 0:
            raise DomainError("The first issue number cannot be negative")
        dates: list[date | None] = (
            [when for _, when in expected_issue_slots(frequency, start, count)]
            if scheduled and start is not None
            else [None] * count
        )
        slots = [(str(first_number + i), when) for i, when in enumerate(dates)]

    existing_numbers = {i.issue_number.casefold() for i in magazine.issues}
    existing_dates = {i.publish_date for i in magazine.issues if i.publish_date}
    created: list[Issue] = []
    for number, when in slots:
        if number.casefold() in existing_numbers or (when is not None and when in existing_dates):
            continue
        issue = Issue(
            issue_number=number,
            publish_date=when,
            sort_index=compute_sort_index(number, when),
            monitored=monitored,
        )
        resolve_status(issue)
        magazine.issues.append(issue)
        created.append(issue)
    check_magazine_collisions(magazine, get_scheme(session))
    session.flush()
    return GenerateResult(created=created, skipped=len(slots) - len(created))
