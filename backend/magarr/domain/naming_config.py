"""Persistence and collision checks for the naming scheme."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from magarr.domain.errors import ConflictError
from magarr.domain.models import Issue, Magazine, NamingConfig
from magarr.domain.naming import (
    IssueNamingInput,
    NamingScheme,
    find_collisions,
    issue_relative_path,
    validate_scheme,
)


def _row(session: Session) -> NamingConfig | None:
    return session.scalar(select(NamingConfig).order_by(NamingConfig.id).limit(1))


def ensure_naming_config(session: Session) -> None:
    if _row(session) is None:
        session.add(NamingConfig(**asdict(NamingScheme())))
        session.flush()


def get_scheme(session: Session) -> NamingScheme:
    row = _row(session)
    if row is None:
        return NamingScheme()
    return NamingScheme(
        magazine_folder_pattern=row.magazine_folder_pattern,
        year_folder_pattern=row.year_folder_pattern,
        issue_file_pattern=row.issue_file_pattern,
        replace_illegal_characters=row.replace_illegal_characters,
        colon_replacement=row.colon_replacement,
    )


def naming_input(magazine: Magazine, issue: Issue, with_file: bool = True) -> IssueNamingInput:
    file = issue.file if with_file else None
    return IssueNamingInput(
        magazine_title=magazine.title,
        issue_number=issue.issue_number,
        first_issue_year=magazine.first_issue_year,
        publisher=magazine.publisher,
        issue_title=issue.title,
        publish_date=issue.publish_date,
        format=file.format if file else None,
        quality=file.quality if file else None,
    )


def check_magazine_collisions(
    magazine: Magazine,
    scheme: NamingScheme,
    template: str | None = None,
    issues: Iterable[Issue] | None = None,
) -> None:
    """Raise if two issues of one magazine would render to the same file name."""
    template = template if template is not None else magazine.issue_naming_template
    # Compare without extension: two formats of one name still collide for upgrades.
    paths = {
        id(issue): issue_relative_path(
            naming_input(magazine, issue, with_file=False), scheme, template
        )
        for issue in (issues if issues is not None else magazine.issues)
    }
    if collisions := find_collisions(paths):
        _, _, path = collisions[0]
        raise ConflictError(
            f"Naming would give more than one issue of '{magazine.title}' the file name "
            f"'{path}'. Issue numbers that differ only by case or illegal characters collide."
        )


def update_scheme(session: Session, scheme: NamingScheme) -> NamingScheme:
    validate_scheme(scheme)
    magazines = session.scalars(
        select(Magazine).options(selectinload(Magazine.issues).selectinload(Issue.file))
    )
    for magazine in magazines:
        check_magazine_collisions(magazine, scheme)

    row = _row(session)
    if row is None:
        row = NamingConfig()
        session.add(row)
    for key, value in asdict(scheme).items():
        setattr(row, key, value)
    session.flush()
    return scheme
