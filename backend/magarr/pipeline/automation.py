"""Set-and-forget operation (brief §5 Phase 5): RSS sync, backlog search, expected issues.

* **Expected issues** roll each monitored magazine's schedule forward (wanted).
* **RSS sync** fetches each indexer's newest releases (a search with no term) and grabs the best
  approved release for any monitored, wanted issue they match. Only releases not seen before
  are evaluated. An indexer whose feed comes back empty is asked per magazine title instead.
* **Backlog search** searches wanted issues a batch at a time: never searched first, oldest
  issue first, then the least recently searched. ``last_searched_at`` is the resumable cursor,
  so a restart carries on where it left off. Each issue stops at its first grab.

The scheduler runs the jobs one after another (never in parallel, so indexer rate limits hold),
and every grab takes the issue lock shared with manual grabs and failed-download retries.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import Select, delete, or_, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from magarr.core.events import EventBus
from magarr.domain.automation_settings import get_automation_settings
from magarr.domain.backups import create_backup
from magarr.domain.enums import IssueStatus
from magarr.domain.errors import DomainError
from magarr.domain.expected import roll_expected_issues
from magarr.domain.issues import compute_sort_index, resolve_status
from magarr.domain.models import AutomationSettings, Indexer, Issue, Magazine, TaskRun
from magarr.importers.matching import match_issue, match_magazine, specialise
from magarr.importers.parsing import ParsedRelease, parse_release
from magarr.indexers import health
from magarr.indexers.client import IndexerRelease, IndexerRequestError, NewznabClient
from magarr.indexers.runtime import IndexerRuntime
from magarr.indexers.service import endpoint_for
from magarr.notifications.dispatch import notify
from magarr.notifications.events import NotificationEvent
from magarr.pipeline.decision import load_context, profile_rejections, rank_key
from magarr.pipeline.grab import grab_release
from magarr.pipeline.health import HealthReport, check_health
from magarr.pipeline.search import applies_to, evaluate, search_issue
from magarr.pipeline.tracking import PollSummary, poll_once

logger = logging.getLogger(__name__)

RSS_SEEN_LIMIT = 2000  # remembered guids per indexer
RESEARCH_AFTER = timedelta(hours=24)  # the backlog won't search the same issue more often
BACKLOG_DAYS_AHEAD = 7  # issues due within a week may already be out
EXPECTED_EVERY_MINUTES = 60


def searchable(issue: Issue, magazine: Magazine) -> bool:
    """Whether automatic searches should look for this issue at all."""
    if not magazine.monitored or not issue.monitored or issue.status != IssueStatus.WANTED:
        return False
    cutoff = magazine.search_cutoff
    return not (cutoff and issue.publish_date and issue.publish_date < cutoff)


def _active_indexers(session: Session) -> list[Indexer]:
    return [
        i
        for i in session.scalars(
            select(Indexer)
            .where(Indexer.enabled.is_(True))
            .order_by(Indexer.priority, Indexer.name)
            # Fresh health: another session (RSS, a search from the UI) may have backed one off.
            .execution_options(populate_existing=True)
        )
        if health.disabled_until(i) is None
    ]


# --- RSS sync ----------------------------------------------------------------------------------


def _is_new_special(parsed: ParsedRelease, magazine: Magazine) -> bool:
    """A special the magazine doesn't have yet, which it wants RSS to pick up."""
    return bool(
        magazine.grab_new_specials
        and parsed.special
        and parsed.number is None
        and parsed.volume is None
        and parsed.issue_key
        and len(parsed.issue_key) <= 100
    )


@dataclass
class RssResult:
    indexers: int = 0
    releases: int = 0
    new: int = 0
    grabbed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def _unseen(runtime: IndexerRuntime, indexer_id: int, releases: Iterable[IndexerRelease]):
    seen = runtime.rss_seen.setdefault(indexer_id, {})
    fresh = []
    for release in releases:
        if release.guid not in seen:
            seen[release.guid] = None
            fresh.append(release)
    while len(seen) > RSS_SEEN_LIMIT:
        del seen[next(iter(seen))]  # oldest first: dicts keep insertion order
    return fresh


async def _feed(
    client: NewznabClient, indexer: Indexer, magazines: list[Magazine]
) -> list[IndexerRelease]:
    releases = await client.recent()
    if releases:
        return releases
    # Some indexers need a search term: ask for each wanted magazine instead.
    found: dict[str, IndexerRelease] = {}
    for magazine in magazines:
        if applies_to(indexer, magazine) and any(searchable(i, magazine) for i in magazine.issues):
            for release in await client.search(magazine.title, max_pages=1):
                found.setdefault(release.guid, release)
    return list(found.values())


async def rss_sync(session: Session, runtime: IndexerRuntime) -> RssResult:
    result = RssResult()
    magazines = list(
        session.scalars(
            select(Magazine)
            .where(Magazine.monitored.is_(True))
            .options(selectinload(Magazine.issues))
        )
    )
    if not any(searchable(i, m) for m in magazines for i in m.issues):
        return result  # nothing wanted: save the indexers' API limits

    candidates: list[tuple[Indexer, IndexerRelease]] = []
    for indexer in _active_indexers(session):
        result.indexers += 1
        client = NewznabClient(endpoint_for(indexer), runtime)
        try:
            releases = await _feed(client, indexer, magazines)
        except IndexerRequestError as exc:
            health.record_failure(indexer, str(exc))
            result.errors[indexer.name] = str(exc)
            logger.warning("RSS sync failed", extra={"indexer": indexer.name, "error": str(exc)})
            continue
        health.record_success(indexer)
        result.releases += len(releases)
        fresh = _unseen(runtime, indexer.id, releases)
        result.new += len(fresh)
        candidates.extend((indexer, r) for r in fresh)
    session.commit()

    # Best approved release per issue.
    best: dict[int, tuple[tuple, Issue, IndexerRelease]] = {}
    for indexer, release in candidates:
        parsed = parse_release(release.title)
        if parsed.is_pack or not parsed.title:
            continue
        magazine = match_magazine(parsed.title, [m for m in magazines if applies_to(indexer, m)])
        if magazine is None:
            continue
        parsed = specialise(parsed, magazine)
        issue = match_issue(parsed, magazine.issues)
        new_special = issue is None and _is_new_special(parsed, magazine)
        if new_special:
            issue = Issue(
                issue_number=parsed.issue_key,
                publish_date=parsed.publish_date,
                sort_index=compute_sort_index(parsed.issue_key, parsed.publish_date),
                monitored=True,
            )
            resolve_status(issue)
        if issue is None or not searchable(issue, magazine):
            continue
        item = evaluate(release, magazine, issue)
        if not item.approved:
            continue
        if new_special:
            # Only now that a release for it has passed the checks.
            magazine.issues.append(issue)
            session.flush()
            logger.info(
                "Added special from RSS",
                extra={"magazine": magazine.title, "issue": issue.issue_number},
            )
        context = load_context(session, issue)
        if reasons := profile_rejections(release, item.quality, context):
            logger.debug("RSS release rejected", extra={"release": release.title, "why": reasons})
            continue
        rank = rank_key(release, item.quality, context, indexer.priority)
        if issue.id not in best or rank < best[issue.id][0]:
            best[issue.id] = (rank, issue, release)

    for _, issue, release in best.values():
        async with runtime.issue_lock(issue.id):
            # A manual grab or another job may have got there first.
            if load_context(session, issue).has_active_download:
                continue
            try:
                await grab_release(session, runtime, issue, release, source="RSS sync")
            except DomainError as exc:
                logger.warning(
                    "RSS grab failed", extra={"release": release.title, "error": exc.message}
                )
                session.rollback()
                continue
            session.commit()
            result.grabbed.append(release.title)
    return result


# --- Backlog / wanted search -------------------------------------------------------------------


@dataclass
class SearchOutcome:
    searched: bool  # at least one indexer answered
    grabbed: str | None = None


async def search_and_grab(
    session: Session, runtime: IndexerRuntime, issue: Issue, source: str, now: datetime
) -> SearchOutcome:
    """Search one issue on every indexer and grab the best approved release."""
    async with runtime.issue_lock(issue.id):
        result = await search_issue(session, runtime, issue)
        if not any(o.ok for o in result.indexers):
            session.commit()  # keep indexer health updates
            return SearchOutcome(searched=False)
        issue.last_searched_at = now
        grabbed = None
        if best := next((r for r in result.releases if r.approved), None):
            try:
                await grab_release(session, runtime, issue, best.release, source=source)
                grabbed = best.release.title
            except DomainError as exc:
                logger.warning(
                    "Automatic grab failed",
                    extra={"release": best.release.title, "error": exc.message},
                )
                session.rollback()
                issue = session.get(Issue, issue.id)
                issue.last_searched_at = now
        session.commit()
        return SearchOutcome(searched=True, grabbed=grabbed)


def backlog_query(now: datetime, limit: int) -> Select[tuple[Issue]]:
    """Wanted issues due a search: never searched first, then oldest issue, then least recent.

    Ordered by last_searched_at itself (SQLite sorts NULLs first) so the
    (status, last_searched_at) index serves the order and only ties are sorted."""
    latest_date = now.date() + timedelta(days=BACKLOG_DAYS_AHEAD)
    return (
        select(Issue)
        .join(Magazine, Issue.magazine_id == Magazine.id)
        .where(
            Magazine.monitored.is_(True),
            Issue.monitored.is_(True),
            Issue.status == IssueStatus.WANTED.value,
            or_(Issue.publish_date.is_(None), Issue.publish_date <= latest_date),
            or_(
                Magazine.search_cutoff.is_(None),
                Issue.publish_date.is_(None),
                Issue.publish_date >= Magazine.search_cutoff,
            ),
            or_(Issue.last_searched_at.is_(None), Issue.last_searched_at < now - RESEARCH_AFTER),
        )
        .order_by(
            Issue.last_searched_at.asc().nulls_first(),
            Issue.publish_date.asc().nulls_last(),
            Issue.sort_index,
        )
        .limit(limit)
    )


def backlog_candidates(session: Session, now: datetime, limit: int) -> list[Issue]:
    return list(session.scalars(backlog_query(now, limit)))


@dataclass
class BacklogResult:
    searched: int = 0
    grabbed: list[str] = field(default_factory=list)
    stopped: str | None = None  # why the batch ended early


async def backlog_search(
    session: Session, runtime: IndexerRuntime, batch_size: int, now: datetime | None = None
) -> BacklogResult:
    now = now or datetime.now(UTC)
    result = BacklogResult()
    if not _active_indexers(session):
        result.stopped = "No indexer is available"
        return result
    for issue in backlog_candidates(session, now, batch_size):
        outcome = await search_and_grab(session, runtime, issue, "backlog search", now)
        if not outcome.searched:
            # Every indexer failed: leave the cursor alone and try again next time.
            result.stopped = "No indexer answered"
            break
        result.searched += 1
        if outcome.grabbed:
            result.grabbed.append(outcome.grabbed)
    return result


# --- Scheduler ---------------------------------------------------------------------------------

HEALTH_EVERY_MINUTES = 15
BACKUP_EVERY_MINUTES = 7 * 24 * 60
KEEP_RUNS = 50  # history kept per task


@dataclass(frozen=True)
class TaskSpec:
    name: str
    label: str
    # Paused by the master switch (Settings → Automation).
    gated: bool
    interval: Callable[[AutomationSettings], int]  # minutes; 0 = off


TASKS: tuple[TaskSpec, ...] = (
    TaskSpec("expected", "Add upcoming issues", True, lambda s: EXPECTED_EVERY_MINUTES),
    TaskSpec("rss", "RSS sync", True, lambda s: s.rss_interval_minutes),
    TaskSpec("backlog", "Backlog search", True, lambda s: s.backlog_interval_minutes),
    TaskSpec("health", "Health check", False, lambda s: HEALTH_EVERY_MINUTES),
    TaskSpec("backup", "Backup", False, lambda s: BACKUP_EVERY_MINUTES),
)


@dataclass
class JobStatus:
    last_run: datetime | None = None
    last_result: str | None = None
    ok: bool = True
    duration_ms: int = 0


@dataclass
class TaskInfo:
    name: str
    label: str
    interval_minutes: float  # 0 = off
    paused: bool  # off because automation is paused
    running: bool
    last_run: datetime | None
    last_result: str | None
    last_ok: bool
    last_duration_ms: int
    next_run: datetime | None


@dataclass(frozen=True)
class BackupTarget:
    config_dir: Path
    database: Path


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class Automation:
    """Runs the tasks on their intervals, one at a time, and records every run.

    Also serves "Run now" and wanted-page searches. Health checks and backups are optional so
    tests of the search jobs don't run them.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        runtime: IndexerRuntime,
        events: EventBus | None = None,
        minute_seconds: float = 60.0,
        clock=time.monotonic,
        *,
        health_checks: bool = False,
        backups: BackupTarget | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.runtime = runtime
        self.events = events
        self.minute_seconds = minute_seconds
        self.clock = clock
        self.health_checks = health_checks
        self.backups = backups
        self.poll_seconds = poll_seconds
        self.lock = asyncio.Lock()  # one task (or wanted search) at a time
        self.last_run: dict[str, float] = {}
        self.status: dict[str, JobStatus] = {}
        self.health: HealthReport | None = None
        self.running: set[str] = set()
        self._history_loaded = False
        self._pending: list[int] = []  # wanted-page searches, in order
        self._tasks: set[asyncio.Task] = set()

    @property
    def specs(self) -> list[TaskSpec]:
        enabled = {"health": self.health_checks, "backup": self.backups is not None}
        return [t for t in TASKS if enabled.get(t.name, True)]

    def _spec(self, name: str) -> TaskSpec | None:
        return next((t for t in self.specs if t.name == name), None)

    def _due(self, name: str, every_minutes: int) -> bool:
        if every_minutes <= 0:
            return False
        last = self.last_run.get(name)
        return last is None or self.clock() - last >= every_minutes * self.minute_seconds

    def _notify(self) -> None:
        if self.events is not None:
            self.events.publish("queue")

    def _load_history(self, session: Session) -> None:
        """After a restart, carry on from the last recorded runs (no backup on every start)."""
        if self._history_loaded:
            return
        self._history_loaded = True
        now = datetime.now(UTC)
        for spec in self.specs:
            run = session.scalar(
                select(TaskRun).where(TaskRun.name == spec.name).order_by(TaskRun.started_at.desc())
            )
            if run is None:
                continue
            started = _aware(run.started_at)
            ago = (now - started).total_seconds() / 60 * self.minute_seconds
            self.last_run[spec.name] = self.clock() - ago
            self.status[spec.name] = JobStatus(started, run.result, run.ok, run.duration_ms)

    # The work itself: each returns a one-line summary.

    async def _expected(self, session: Session, settings: AutomationSettings) -> str:
        rolled = roll_expected_issues(session, date.today(), settings.expected_lookahead_days)
        session.commit()
        return f"{len(rolled.created)} issue(s) added"

    async def _rss(self, session: Session, settings: AutomationSettings) -> str:
        rss = await rss_sync(session, self.runtime)
        if rss.grabbed:
            self._notify()
            logger.info("RSS sync grabbed", extra={"releases": rss.grabbed})
        failed = f", {len(rss.errors)} indexer(s) failed" if rss.errors else ""
        return f"{rss.new} new release(s), {len(rss.grabbed)} grabbed{failed}"

    async def _backlog(self, session: Session, settings: AutomationSettings) -> str:
        backlog = await backlog_search(session, self.runtime, settings.backlog_batch_size)
        if backlog.grabbed:
            self._notify()
        return backlog.stopped or f"{backlog.searched} searched, {len(backlog.grabbed)} grabbed"

    async def _health(self, session: Session, settings: AutomationSettings) -> str:
        before = {i.message for i in self.health.problems} if self.health else set()
        self.health = await check_health(session, self.runtime)
        for item in self.health.problems:
            if item.message not in before:  # only new problems, not every 15 minutes
                notify(NotificationEvent.HEALTH, message=item.message, source=item.source)
        problems = self.health.problems
        return f"{len(problems)} problem(s)" if problems else "Everything is healthy"

    async def _backup(self, session: Session, settings: AutomationSettings) -> str:
        target = self.backups
        if target is None:  # only registered when backups are configured
            return "Backups are not configured"
        info = await asyncio.to_thread(
            create_backup, target.config_dir, target.database, "scheduled"
        )
        return f"Saved {info.name}"

    async def _run(self, spec: TaskSpec, session: Session, manual: bool = False) -> None:
        settings = get_automation_settings(session)
        work = getattr(self, f"_{spec.name}")
        started, began = datetime.now(UTC), time.monotonic()
        self.running.add(spec.name)
        try:
            summary, ok = await work(session, settings), True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Task failed", extra={"task": spec.name})
            session.rollback()
            summary, ok = f"Failed: {exc}"[:1024], False
        finally:
            self.running.discard(spec.name)
        duration = int((time.monotonic() - began) * 1000)
        self.last_run[spec.name] = self.clock()
        self.status[spec.name] = JobStatus(started, summary, ok, duration)
        session.add(
            TaskRun(
                name=spec.name,
                started_at=started,
                duration_ms=duration,
                ok=ok,
                result=summary,
                manual=manual,
            )
        )
        old = session.scalars(
            select(TaskRun.id)
            .where(TaskRun.name == spec.name)
            .order_by(TaskRun.started_at.desc())
            .offset(KEEP_RUNS)
        ).all()
        if old:
            session.execute(delete(TaskRun).where(TaskRun.id.in_(old)))
        session.commit()

    async def tick(self) -> None:
        async with self.lock:
            with self.session_factory() as session:
                self._load_history(session)
                settings = get_automation_settings(session)
                session.commit()
                for spec in self.specs:
                    if spec.gated and not settings.monitoring_enabled:
                        continue
                    if self._due(spec.name, spec.interval(settings)):
                        await self._run(spec, session)

    def run_now(self, name: str) -> bool:
        """Start a task straight away ("downloads" checks the download clients)."""
        if name == "downloads":
            if self.poll_seconds is None:
                return False
            self._background(self._poll(), "downloads")
            return True
        spec = self._spec(name)
        if spec is None or name in self.running:
            return False

        async def go() -> None:
            async with self.lock:
                with self.session_factory() as session:
                    self._load_history(session)
                    await self._run(spec, session, manual=True)

        self._background(go(), name)
        return True

    async def _poll(self) -> None:
        with self.session_factory() as session:
            summary = await poll_once(session, self.runtime)
        self.record_poll(summary)
        self._notify()

    def record_poll(self, summary: PollSummary) -> None:
        """The download poller runs on its own loop; this keeps its last result for Tasks."""
        result = f"{summary.checked} checked, {len(summary.imported)} imported"
        if summary.client_errors:
            result += f", {len(summary.client_errors)} client(s) unreachable"
        self.status["downloads"] = JobStatus(
            datetime.now(UTC), result, not summary.client_errors, 0
        )

    def tasks(self) -> list[TaskInfo]:
        with self.session_factory() as session:
            settings = get_automation_settings(session)
            session.commit()
        infos = []
        if self.poll_seconds is not None:
            status = self.status.get("downloads", JobStatus())
            infos.append(
                TaskInfo(
                    "downloads", "Check downloads", self.poll_seconds / 60, False, False,
                    status.last_run, status.last_result, status.ok, status.duration_ms,
                    None if status.last_run is None
                    else status.last_run + timedelta(seconds=self.poll_seconds),
                )
            )  # fmt: skip
        for spec in self.specs:
            status = self.status.get(spec.name, JobStatus())
            minutes = spec.interval(settings)
            paused = spec.gated and not settings.monitoring_enabled
            if paused or minutes <= 0:
                next_run = None
            elif status.last_run is None:
                next_run = datetime.now(UTC)
            else:
                next_run = status.last_run + timedelta(minutes=minutes)
            infos.append(
                TaskInfo(
                    spec.name, spec.label, minutes, paused, spec.name in self.running,
                    status.last_run, status.last_result, status.ok, status.duration_ms, next_run,
                )
            )  # fmt: skip
        return infos

    def history(self, name: str, limit: int = KEEP_RUNS) -> list[TaskRun]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(TaskRun)
                    .where(TaskRun.name == name)
                    .order_by(TaskRun.started_at.desc())
                    .limit(limit)
                )
            )

    def _background(self, coro, name: str) -> None:
        task = asyncio.create_task(coro, name=f"task-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def search_issues(self, issue_ids: list[int]) -> int:
        """Queue issues for an automatic search (wanted page); returns how many were added."""
        new = [i for i in issue_ids if i not in self._pending]
        self._pending.extend(new)
        if new:
            self._background(self._drain(), "wanted-search")
        return len(new)

    async def _drain(self) -> None:
        async with self.lock:
            with self.session_factory() as session:
                while self._pending:
                    issue = session.get(Issue, self._pending.pop(0))
                    if issue is None or issue.file is not None:
                        continue
                    try:
                        outcome = await search_and_grab(
                            session, self.runtime, issue, "wanted search", datetime.now(UTC)
                        )
                    except Exception:
                        logger.exception("Wanted search crashed", extra={"issue_id": issue.id})
                        session.rollback()
                        continue
                    if outcome.grabbed:
                        self._notify()

    async def run(self, tick_seconds: float) -> None:
        """Background loop started with the app."""
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Automation run crashed; will retry next tick")

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
