from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from magarr.domain.enums import IssueStatus
from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.issues import compute_sort_index, resolve_status
from magarr.domain.magazines import get_magazine
from magarr.domain.models import Issue
from magarr.domain.naming_config import check_magazine_collisions, get_scheme


@dataclass
class IssueFields:
    """Writable issue fields. On update, only names in ``provided`` are applied."""

    issue_number: str | None = None
    title: str | None = None
    publish_date: date | None = None
    cover_url: str | None = None
    monitored: bool | None = None
    status: IssueStatus | None = None
    sort_index: float | None = None
    provided: set[str] = field(default_factory=set)


def get_issue(session: Session, issue_id: int) -> Issue:
    issue = session.get(Issue, issue_id)
    if issue is None:
        raise NotFoundError(f"Issue {issue_id} not found")
    return issue


def _check_number(issue: Issue | None, magazine_issues: list[Issue], number: str) -> str:
    number = number.strip()
    if not number:
        raise DomainError("Issue number cannot be empty")
    for other in magazine_issues:
        if other is not issue and other.issue_number.casefold() == number.casefold():
            raise ConflictError(f"Issue '{number}' already exists")
    return number


def _check_status(status: IssueStatus | None) -> None:
    if status is IssueStatus.DOWNLOADED:
        raise DomainError("Status 'downloaded' is set by importing a file, not directly")


def create_issue(session: Session, magazine_id: int, fields: IssueFields) -> Issue:
    magazine = get_magazine(session, magazine_id)
    _check_status(fields.status)
    number = _check_number(None, magazine.issues, fields.issue_number or "")
    issue = Issue(
        issue_number=number,
        title=fields.title,
        publish_date=fields.publish_date,
        cover_url=fields.cover_url,
        monitored=bool(fields.monitored),
        sort_index=(
            fields.sort_index
            if fields.sort_index is not None
            else compute_sort_index(number, fields.publish_date)
        ),
    )
    resolve_status(issue, fields.status)
    magazine.issues.append(issue)
    check_magazine_collisions(magazine, get_scheme(session))
    session.flush()
    return issue


def update_issue(session: Session, issue_id: int, fields: IssueFields) -> Issue:
    issue = get_issue(session, issue_id)
    _check_status(fields.status)
    values: dict[str, Any] = {name: getattr(fields, name) for name in fields.provided}
    status = values.pop("status", None)

    if "issue_number" in values:
        values["issue_number"] = _check_number(
            issue, issue.magazine.issues, values["issue_number"] or ""
        )
    if "monitored" in values and values["monitored"] is None:
        raise DomainError("monitored cannot be null")
    for name, value in values.items():
        setattr(issue, name, value)
    if "sort_index" not in values and {"issue_number", "publish_date"} & values.keys():
        issue.sort_index = compute_sort_index(issue.issue_number, issue.publish_date)
    resolve_status(issue, status)
    if {"issue_number", "title", "publish_date"} & values.keys():
        check_magazine_collisions(issue.magazine, get_scheme(session))
    session.flush()
    return issue


def bulk_update(
    session: Session, ids: list[int], monitored: bool | None, status: IssueStatus | None
) -> list[Issue]:
    _check_status(status)
    if monitored is None and status is None:
        raise DomainError("Provide monitored or status")
    issues = list(session.scalars(select(Issue).where(Issue.id.in_(ids))))
    if missing := set(ids) - {i.id for i in issues}:
        raise NotFoundError(f"Issue(s) not found: {', '.join(map(str, sorted(missing)))}")
    for issue in issues:
        if monitored is not None:
            issue.monitored = monitored
        resolve_status(issue, status)
    session.flush()
    return issues


def delete_issue(session: Session, issue_id: int) -> None:
    """Removes the issue record (and its file record). The file on disk is left alone."""
    issue = get_issue(session, issue_id)
    issue.magazine.issues.remove(issue)
    session.flush()
