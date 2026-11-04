"""Roll each monitored magazine's schedule forward: upcoming issues are created as wanted.

The next issues follow on from the latest dated issue, in the same numbering style
("2026-07", "2026-W27", "2026-Q3", or a plain number such as "361"), up to
``lookahead_days`` ahead so an issue released early already exists when RSS sees it.
A magazine whose latest issue is more than ``ACTIVE_PERIODS`` periods old has most likely
stopped (or the library is incomplete), so nothing is invented for it; slots more than two
periods in the past are skipped too. Filling old gaps is the user's call (Generate issues).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from magarr.domain.enums import Frequency
from magarr.domain.issues import compute_sort_index, expected_issue_slots, resolve_status
from magarr.domain.models import Issue, Magazine

logger = logging.getLogger(__name__)

PERIOD_DAYS = {Frequency.WEEKLY: 7, Frequency.MONTHLY: 31, Frequency.QUARTERLY: 92}
ACTIVE_PERIODS = 6  # latest issue older than this many periods: treated as no longer published
_MAX_SLOTS = 2000  # weekly for ~40 years: enough to walk from any latest issue to today

_STYLES = (
    ("day", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("week", re.compile(r"^\d{4}-W\d{2}$", re.IGNORECASE)),
    ("quarter", re.compile(r"^\d{4}-Q[1-4]$", re.IGNORECASE)),
    ("month", re.compile(r"^\d{4}-\d{2}$")),
    ("number", re.compile(r"^\d+$")),
)


@dataclass
class RollResult:
    created: list[Issue] = field(default_factory=list)
    magazines: list[str] = field(default_factory=list)


def _style(issue_number: str) -> str | None:
    return next((name for name, pattern in _STYLES if pattern.match(issue_number.strip())), None)


def _key(style: str, when: date, number: int) -> str:
    if style == "day":
        return when.isoformat()
    if style == "week":
        iso = when.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if style == "quarter":
        return f"{when.year}-Q{(when.month - 1) // 3 + 1}"
    if style == "month":
        return f"{when.year}-{when.month:02d}"
    return str(number)


def next_issues(magazine: Magazine, today: date, lookahead_days: int) -> list[tuple[str, date]]:
    """(issue_number, publish_date) for upcoming issues that don't exist yet."""
    try:
        frequency = Frequency(magazine.frequency)
    except ValueError:
        return []
    if frequency not in PERIOD_DAYS:
        return []
    # The schedule follows regular issues; specials ("Christmas Special 2024") are extras.
    dated = [i for i in magazine.issues if i.publish_date and _style(i.issue_number)]
    if not dated:
        return []
    latest = max(dated, key=lambda i: (i.publish_date, i.sort_index))
    if latest.publish_date < today - timedelta(days=ACTIVE_PERIODS * PERIOD_DAYS[frequency]):
        return []
    style = _style(latest.issue_number)

    horizon = today + timedelta(days=lookahead_days)
    oldest = today - timedelta(days=2 * PERIOD_DAYS[frequency])
    numbers = {i.issue_number.casefold() for i in magazine.issues}
    dates = {i.publish_date for i in dated}
    first_number = int(latest.issue_number) if style == "number" else 0

    found: list[tuple[str, date]] = []
    slots = expected_issue_slots(frequency, latest.publish_date, _MAX_SLOTS)
    for offset, (_, when) in enumerate(slots[1:], start=1):
        if when > horizon:
            break
        if when < oldest:
            continue
        key = _key(style, when, first_number + offset)
        if key.casefold() in numbers or when in dates:
            continue
        found.append((key, when))
    return found


def roll_expected_issues(session: Session, today: date, lookahead_days: int) -> RollResult:
    result = RollResult()
    magazines = session.scalars(select(Magazine).where(Magazine.monitored.is_(True)))
    for magazine in magazines:
        upcoming = next_issues(magazine, today, lookahead_days)
        for number, when in upcoming:
            issue = Issue(
                issue_number=number,
                publish_date=when,
                sort_index=compute_sort_index(number, when),
                monitored=True,
            )
            resolve_status(issue)
            magazine.issues.append(issue)
            result.created.append(issue)
        if upcoming:
            result.magazines.append(magazine.title)
            logger.info(
                "Added expected issues",
                extra={"magazine": magazine.title, "issues": [n for n, _ in upcoming]},
            )
    session.flush()
    return result
