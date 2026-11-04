"""Failure tracking: repeatedly failing indexers are skipped for an escalating period."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import object_session
from sqlalchemy.orm.attributes import set_committed_value

from magarr.core.logging import redact
from magarr.domain.models import Indexer

# Failures tolerated before an indexer is temporarily disabled.
FAILURE_THRESHOLD = 3
BACKOFF = [
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
    timedelta(hours=12),
    timedelta(hours=24),
]


def _aware(value: datetime | None) -> datetime | None:
    # SQLite drops tzinfo; everything Magarr stores is UTC.
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def disabled_until(indexer: Indexer, now: datetime | None = None) -> datetime | None:
    """When the indexer becomes usable again, or None if it is usable now."""
    until = _aware(indexer.disabled_until)
    now = now or datetime.now(UTC)
    return until if until and until > now else None


def record_success(indexer: Indexer, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    values = {
        "consecutive_failures": 0,
        "disabled_until": None,
        "last_error": None,
        "last_success": now,
    }
    _store(indexer, values)


def record_failure(indexer: Indexer, error: str, now: datetime | None = None) -> None:
    """Count a failure; past the threshold, skip the indexer for an escalating time.

    The count is incremented in the database (UPDATE ... SET n = n + 1), because the backlog,
    RSS sync and interactive searches each hold their own session: adding to a stale copy would
    let them overwrite each other's counts and the back-off would never kick in."""
    now = now or datetime.now(UTC)
    error = redact(error)[:1024]
    session = object_session(indexer)
    if session is None or indexer.id is None:  # not saved yet (e.g. testing settings)
        failures = (indexer.consecutive_failures or 0) + 1
    else:
        failures = session.execute(
            update(Indexer)
            .where(Indexer.id == indexer.id)
            .values(consecutive_failures=Indexer.consecutive_failures + 1)
            .returning(Indexer.consecutive_failures)
            .execution_options(synchronize_session=False)
        ).scalar_one()
    values: dict = {"consecutive_failures": failures, "last_error": error}
    if failures >= FAILURE_THRESHOLD:
        step = min(failures - FAILURE_THRESHOLD, len(BACKOFF) - 1)
        values["disabled_until"] = now + BACKOFF[step]
    _store(indexer, values)


def _store(indexer: Indexer, values: dict) -> None:
    """Write ``values`` straight to the database (when the indexer is saved) and to the object,
    without marking the object dirty, so a later flush can't put back an older count."""
    session = object_session(indexer)
    if session is not None and indexer.id is not None:
        session.execute(
            update(Indexer)
            .where(Indexer.id == indexer.id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        for key, value in values.items():
            set_committed_value(indexer, key, value)
    else:
        for key, value in values.items():
            setattr(indexer, key, value)
