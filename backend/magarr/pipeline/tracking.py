"""Track grabbed downloads in their clients (brief §5 Phase 3: queue polling and failure handling).

Each poll asks every client about its active downloads, then:
  completed -> pending_import (+ history), ready for the Phase 4 import pipeline
  failed    -> failed (+ history), release blocklisted, and optionally the next-best grabbed
               (at most ``max_retries`` times per issue; then it waits for the user)
  missing   -> after MISSING_POLLS_BEFORE_WARNING polls, marked warning (not failed: the user may
               have moved it, and failing would trigger a re-download)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from magarr.core.events import EventBus
from magarr.domain.download_clients import get_download_settings
from magarr.domain.enums import (
    ACTIVE_DOWNLOAD_STATUSES,
    DownloadClientImplementation,
    DownloadStatus,
    HistoryEventType,
)
from magarr.domain.errors import DomainError
from magarr.domain.history import record
from magarr.domain.media_settings import get_media_settings
from magarr.domain.models import BlocklistItem, Download, DownloadClient, Issue
from magarr.downloaders.base import ClientItem, ClientItemStatus, DownloadClientError
from magarr.downloaders.registry import build_client
from magarr.importers.importer import import_download
from magarr.indexers.runtime import IndexerRuntime
from magarr.pipeline.grab import grab_release
from magarr.pipeline.search import search_issue

logger = logging.getLogger(__name__)

MISSING_POLLS_BEFORE_WARNING = 3

_CLIENT_TO_DOWNLOAD = {
    ClientItemStatus.QUEUED: DownloadStatus.QUEUED,
    ClientItemStatus.DOWNLOADING: DownloadStatus.DOWNLOADING,
    ClientItemStatus.PAUSED: DownloadStatus.PAUSED,
}


@dataclass
class PollSummary:
    checked: int = 0
    completed: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    retried: list[int] = field(default_factory=list)  # issue ids re-grabbed after a failure
    imported: list[int] = field(default_factory=list)  # download ids imported this poll
    client_errors: dict[str, str] = field(default_factory=dict)


def _apply(download: Download, item: ClientItem) -> None:
    download.missing_polls = 0
    download.progress = max(0.0, min(item.progress, 1.0))
    download.size = item.size or download.size
    download.size_left = item.size_left
    download.message = item.message
    if item.status in _CLIENT_TO_DOWNLOAD:
        download.status = _CLIENT_TO_DOWNLOAD[item.status].value


def mark_completed(session: Session, download: Download, item: ClientItem) -> None:
    _apply(download, item)
    download.status = DownloadStatus.PENDING_IMPORT.value
    download.progress = 1.0
    download.size_left = 0
    download.output_path = item.output_path
    download.completed_at = datetime.now(UTC)
    record(
        session,
        HistoryEventType.DOWNLOAD_COMPLETED,
        download.title,
        download.issue,
        download_id=download.id,
        output_path=item.output_path,
    )
    logger.info("Download completed", extra={"release": download.title, "path": item.output_path})


def mark_failed(session: Session, download: Download, message: str) -> None:
    download.status = DownloadStatus.FAILED.value
    download.message = message
    record(
        session,
        HistoryEventType.DOWNLOAD_FAILED,
        download.title,
        download.issue,
        download_id=download.id,
        message=message,
    )
    session.add(
        BlocklistItem(
            issue_id=download.issue_id,
            magazine_id=download.issue.magazine_id if download.issue else None,
            guid=download.release.get("guid", ""),
            indexer_id=download.release.get("indexer_id"),
            source_title=download.title,
            protocol=download.protocol,
            reason=message,
        )
    )
    logger.warning("Download failed", extra={"release": download.title, "reason": message})


async def grab_best(
    session: Session, runtime: IndexerRuntime, issue: Issue, source: str
) -> Download | None:
    """Search and grab the top approved release, if any. Takes the issue lock."""
    async with runtime.issue_lock(issue.id):
        result = await search_issue(session, runtime, issue)
        best = next((r for r in result.releases if r.approved), None)
        if best is None:
            logger.info("No acceptable release to grab", extra={"issue_id": issue.id})
            return None
        return await grab_release(session, runtime, issue, best.release, source=source)


async def poll_once(session: Session, runtime: IndexerRuntime) -> PollSummary:
    summary = PollSummary()
    active = list(
        session.scalars(
            select(Download)
            .where(Download.status.in_([s.value for s in ACTIVE_DOWNLOAD_STATUSES]))
            .options(selectinload(Download.issue).selectinload(Issue.magazine))
        )
    )
    by_client: dict[int | None, list[Download]] = defaultdict(list)
    for download in active:
        by_client[download.download_client_id].append(download)

    failed: list[Download] = []
    for client_id, downloads in by_client.items():
        row = session.get(DownloadClient, client_id) if client_id is not None else None
        if row is None:
            for download in downloads:
                download.status = DownloadStatus.WARNING.value
                download.message = "The download client was removed from Magarr"
            continue
        client = build_client(
            DownloadClientImplementation(row.implementation), row.settings, runtime.http
        )
        try:
            items = await client.items({d.external_id for d in downloads})
        except DownloadClientError as exc:
            summary.client_errors[row.name] = str(exc)
            logger.warning(
                "Download client poll failed", extra={"client": row.name, "error": str(exc)}
            )
            continue
        for download in downloads:
            summary.checked += 1
            item = items.get(download.external_id)
            if item is None:
                download.missing_polls += 1
                if download.missing_polls >= MISSING_POLLS_BEFORE_WARNING:
                    download.status = DownloadStatus.WARNING.value
                    download.message = f"No longer found in {row.name}"
            elif item.status is ClientItemStatus.COMPLETED:
                mark_completed(session, download, item)
                summary.completed.append(download.id)
            elif item.status is ClientItemStatus.FAILED:
                _apply(download, item)
                mark_failed(session, download, item.message or "Download failed")
                summary.failed.append(download.id)
                failed.append(download)
            else:
                _apply(download, item)
    session.commit()

    download_settings = get_download_settings(session)
    if failed and download_settings.redownload_failed:
        for download in failed:
            if download.issue is None:
                continue
            failures = session.scalar(
                select(func.count(BlocklistItem.id)).where(
                    BlocklistItem.issue_id == download.issue_id
                )
            )
            if failures > download_settings.max_retries:
                logger.warning(
                    "Not retrying: too many failed downloads for this issue",
                    extra={"issue_id": download.issue_id, "failures": failures},
                )
                continue
            try:
                retry = await grab_best(
                    session, runtime, download.issue, source="automatic retry after failure"
                )
            except DomainError as exc:
                logger.warning(
                    "Automatic retry failed",
                    extra={"issue_id": download.issue_id, "error": exc.message},
                )
                session.rollback()
                continue
            if retry is not None:
                summary.retried.append(download.issue_id)
            session.commit()
    await import_pending(session, runtime, summary)
    return summary


async def import_pending(session: Session, runtime: IndexerRuntime, summary: PollSummary) -> None:
    """Import finished downloads (if automatic import is on) and tidy up the client."""
    settings = get_media_settings(session)
    if not settings.auto_import:
        return
    pending = list(
        session.scalars(
            select(Download).where(Download.status == DownloadStatus.PENDING_IMPORT.value)
        )
    )
    for download in pending:
        try:
            result = import_download(session, download)
        except Exception:
            logger.exception("Import crashed", extra={"download": download.title})
            session.rollback()
            continue
        session.commit()
        if download.status != DownloadStatus.IMPORTED.value:
            continue
        summary.imported.append(download.id)
        moved_everything = not any(o.skipped for o in result.outcomes)
        row = download.download_client
        if (
            settings.remove_completed_downloads
            and moved_everything
            and download.protocol == "usenet"
            and settings.usenet_import_mode == "move"
            and row is not None
        ):
            client = build_client(
                DownloadClientImplementation(row.implementation), row.settings, runtime.http
            )
            try:
                await client.remove(download.external_id, delete_data=False)
            except DownloadClientError as exc:
                logger.warning(
                    "Could not remove the download from the client", extra={"error": str(exc)}
                )


async def run_poller(
    session_factory: sessionmaker[Session],
    runtime: IndexerRuntime,
    interval: float,
    events: EventBus | None = None,
    on_poll: Callable[[PollSummary], None] | None = None,
) -> None:
    """Background loop started with the app; one poll every ``interval`` seconds."""
    while True:
        await asyncio.sleep(interval)
        try:
            with session_factory() as session:
                summary = await poll_once(session, runtime)
            if events is not None and summary.checked + len(summary.imported):
                events.publish("queue")
            if on_poll is not None:
                on_poll(summary)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Download poll crashed; will retry next interval")
