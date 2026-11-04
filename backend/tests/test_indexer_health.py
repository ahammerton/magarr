from datetime import UTC, datetime, timedelta

from magarr.domain.models import Indexer
from magarr.indexers import health

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_disabled_after_threshold_with_escalating_backoff() -> None:
    indexer = Indexer(consecutive_failures=0)
    for _ in range(health.FAILURE_THRESHOLD - 1):
        health.record_failure(indexer, "boom", NOW)
    assert health.disabled_until(indexer, NOW) is None

    health.record_failure(indexer, "boom", NOW)
    assert health.disabled_until(indexer, NOW) == NOW + timedelta(minutes=5)
    health.record_failure(indexer, "boom", NOW)
    assert health.disabled_until(indexer, NOW) == NOW + timedelta(minutes=15)
    for _ in range(20):
        health.record_failure(indexer, "boom", NOW)
    assert health.disabled_until(indexer, NOW) == NOW + timedelta(hours=24)  # capped
    assert indexer.last_error == "boom"


def test_success_resets() -> None:
    indexer = Indexer(
        consecutive_failures=7, disabled_until=NOW + timedelta(hours=1), last_error="x"
    )
    health.record_success(indexer, NOW)
    assert (indexer.consecutive_failures, indexer.disabled_until, indexer.last_error) == (
        0,
        None,
        None,
    )
    assert indexer.last_success == NOW


def test_naive_datetimes_from_sqlite_are_treated_as_utc() -> None:
    indexer = Indexer(disabled_until=(NOW + timedelta(minutes=1)).replace(tzinfo=None))
    assert health.disabled_until(indexer, NOW) == NOW + timedelta(minutes=1)
    assert health.disabled_until(indexer, NOW + timedelta(minutes=2)) is None


def test_stored_errors_are_redacted() -> None:
    indexer = Indexer(consecutive_failures=0)
    health.record_failure(indexer, "Could not reach https://idx/api?apikey=SECRET123", NOW)
    assert indexer.last_error == "Could not reach https://idx/api?apikey=***"


def test_failures_from_separate_sessions_all_count(api) -> None:
    """The backlog, RSS sync and searches from the UI hold separate sessions: a failure recorded
    in one must not be overwritten by another's stale copy (it was, so back-off never started)."""
    from magarr.domain.models import Indexer

    api.post(
        "/api/v1/indexer", json={"name": "Idx", "baseUrl": "https://idx.example", "apiKey": "k"}
    )
    factory = api.app.state.session_factory
    with factory() as backlog, factory() as ui, factory() as rss:
        copies = [s.query(Indexer).one() for s in (backlog, ui, rss)]  # all loaded before
        for session, indexer in zip((backlog, ui, rss), copies, strict=True):
            health.record_failure(indexer, "HTTP 500", NOW)
            session.commit()
    with factory() as session:
        indexer = session.query(Indexer).one()
        assert indexer.consecutive_failures == 3
        assert indexer.disabled_until is not None  # the third failure backs it off
