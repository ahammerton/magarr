"""Issue rules: status resolution, sort keys and expected-issue generation."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from magarr.domain.enums import Frequency, IssueStatus
from magarr.domain.models import Issue

_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_DATE_KEY = re.compile(
    r"^(?P<y>\d{4})(?:-(?:(?P<m>\d{2})(?:-(?P<d>\d{2}))?|Q(?P<q>[1-4])|W(?P<w>\d{2})))?$",
    re.IGNORECASE,
)
_VOL_NO = re.compile(r"^vol(?:ume)?\.?\s*(\d+)\s*no\.?\s*(\d+)$", re.IGNORECASE)


def resolve_status(issue: Issue, requested: IssueStatus | None = None) -> None:
    """Make ``status`` consistent with the file and monitored flag.

    downloaded beats everything; ignored sticks until the issue is monitored again.
    """
    if requested is IssueStatus.WANTED:
        issue.monitored = True
    elif requested in (IssueStatus.MISSING, IssueStatus.IGNORED):
        issue.monitored = False

    if issue.file is not None:
        issue.status = IssueStatus.DOWNLOADED
    elif issue.monitored:
        issue.status = IssueStatus.WANTED
    elif requested is IssueStatus.IGNORED or (
        requested is None and issue.status == IssueStatus.IGNORED
    ):
        issue.status = IssueStatus.IGNORED
    else:
        issue.status = IssueStatus.MISSING


def is_date_key(issue_number: str) -> bool:
    """True for date-style issue numbers: 2024, 2024-05, 2024-05-11, 2024-Q2, 2024-W19."""
    return bool(_DATE_KEY.match(issue_number.strip()))


def compute_sort_index(issue_number: str, publish_date: date | None = None) -> float:
    """A float that orders issues sensibly within one numbering scheme.

    Plain numbers sort as themselves, date keys as YYYYMMDD, Vol/No as vol*1000+no. Anything
    else falls back to the publish date (or 0).
    """
    text = issue_number.strip()
    if _NUMBER.match(text):
        return float(text)
    if match := _DATE_KEY.match(text):
        year = int(match["y"])
        if match["q"]:
            month, day = (int(match["q"]) - 1) * 3 + 1, 1
        elif match["w"]:
            return float(year * 10000 + int(match["w"]))
        else:
            month, day = int(match["m"] or 0), int(match["d"] or 0)
        return float(year * 10000 + month * 100 + day)
    if match := _VOL_NO.match(text):
        return float(int(match[1]) * 1000 + int(match[2]))
    if publish_date:
        return float(publish_date.year * 10000 + publish_date.month * 100 + publish_date.day)
    return 0.0


def _add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def expected_issue_slots(frequency: Frequency, start: date, count: int) -> list[tuple[str, date]]:
    """(issue_number, publish_date) slots for a regular publication schedule."""
    slots: list[tuple[str, date]] = []
    for i in range(count):
        if frequency is Frequency.WEEKLY:
            when = start + timedelta(weeks=i)
            slots.append((when.isoformat(), when))
        elif frequency is Frequency.MONTHLY:
            when = _add_months(start, i)
            slots.append((f"{when.year}-{when.month:02d}", when))
        elif frequency is Frequency.QUARTERLY:
            when = _add_months(start, 3 * i)
            slots.append((f"{when.year}-Q{(when.month - 1) // 3 + 1}", when))
        else:
            raise ValueError("Ad-hoc magazines have no schedule to generate issues from")
    return slots
