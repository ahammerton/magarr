"""RSS sync, backlog search and expected-issue settings (single row)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from magarr.domain.errors import DomainError
from magarr.domain.models import AutomationSettings

MIN_RSS_MINUTES = 10  # indexers ban clients that poll faster
MIN_BACKLOG_MINUTES = 15
_LIMITS = {
    "rss_interval_minutes": (0, 24 * 60),
    "backlog_interval_minutes": (0, 7 * 24 * 60),
    "backlog_batch_size": (1, 100),
    "expected_lookahead_days": (0, 365),
}


def get_automation_settings(session: Session) -> AutomationSettings:
    row = session.scalar(select(AutomationSettings).order_by(AutomationSettings.id).limit(1))
    if row is None:
        row = AutomationSettings(
            monitoring_enabled=True,
            rss_interval_minutes=15,
            backlog_interval_minutes=60,
            backlog_batch_size=10,
            expected_lookahead_days=45,
        )
        session.add(row)
        session.flush()
    return row


def update_automation_settings(session: Session, values: dict[str, Any]) -> AutomationSettings:
    for key, (low, high) in _LIMITS.items():
        if key in values and not low <= values[key] <= high:
            raise DomainError(f"{key} must be between {low} and {high}")
    rss = values.get("rss_interval_minutes")
    if rss and rss < MIN_RSS_MINUTES:
        raise DomainError(f"RSS sync can't run more often than every {MIN_RSS_MINUTES} minutes")
    backlog = values.get("backlog_interval_minutes")
    if backlog and backlog < MIN_BACKLOG_MINUTES:
        raise DomainError(
            f"Backlog search can't run more often than every {MIN_BACKLOG_MINUTES} minutes"
        )
    row = get_automation_settings(session)
    for key, value in values.items():
        setattr(row, key, value)
    session.flush()
    return row
