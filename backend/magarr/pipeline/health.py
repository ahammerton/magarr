"""Health checks: is everything Magarr depends on reachable and sane?

Errors stop things working (a root folder that isn't mounted, a download client that can't be
reached); warnings will cause trouble (low disk space, a failing indexer, blocked imports);
notices are just worth knowing (automation is paused).
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.domain.automation_settings import get_automation_settings
from magarr.domain.enums import DownloadClientImplementation, DownloadStatus
from magarr.domain.models import Download, DownloadClient, Indexer, Notification, RootFolder
from magarr.downloaders.base import DownloadClientError
from magarr.downloaders.registry import build_client
from magarr.indexers import health as indexer_health
from magarr.indexers.runtime import IndexerRuntime

LOW_SPACE_BYTES = 1024**3  # 1 GiB
CLIENT_TIMEOUT = 15.0

Level = Literal["error", "warning", "notice"]


@dataclass(frozen=True)
class HealthItem:
    source: str  # root_folder | indexer | download_client | import | notification | automation
    level: Level
    message: str


@dataclass
class HealthReport:
    checked_at: datetime
    items: list[HealthItem]

    @property
    def problems(self) -> list[HealthItem]:
        return [i for i in self.items if i.level != "notice"]


def _gib(size: int) -> str:
    return f"{size / 1024**3:.1f} GB"


def _root_folders(session: Session) -> list[HealthItem]:
    roots = list(session.scalars(select(RootFolder).order_by(RootFolder.path)))
    if not roots:
        return [HealthItem("root_folder", "warning", "No root folder: add one in Media Management")]
    items = []
    for root in roots:
        path = Path(root.path)
        if not path.is_dir():
            items.append(
                HealthItem(
                    "root_folder", "error", f"Root folder {root.path} is missing (not mounted?)"
                )
            )
            continue
        if not os.access(path, os.W_OK):
            items.append(
                HealthItem("root_folder", "error", f"Magarr can't write to root folder {root.path}")
            )
        free = shutil.disk_usage(path).free
        if free < LOW_SPACE_BYTES:
            items.append(
                HealthItem("root_folder", "warning", f"Only {_gib(free)} free in {root.path}")
            )
    return items


def _indexers(session: Session) -> list[HealthItem]:
    indexers = list(session.scalars(select(Indexer).where(Indexer.enabled.is_(True))))
    if not indexers:
        return [HealthItem("indexer", "warning", "No enabled indexer: nothing can be searched")]
    items = []
    for indexer in indexers:
        if until := indexer_health.disabled_until(indexer):
            items.append(
                HealthItem(
                    "indexer",
                    "warning",
                    f"Indexer {indexer.name} is failing and skipped until "
                    f"{until.astimezone().strftime('%H:%M')}: {indexer.last_error}",
                )
            )
    if len(items) == len(indexers):
        items.append(HealthItem("indexer", "error", "Every indexer is failing"))
    return items


async def _download_clients(session: Session, runtime: IndexerRuntime) -> list[HealthItem]:
    clients = list(session.scalars(select(DownloadClient).where(DownloadClient.enabled.is_(True))))
    if not clients:
        return [
            HealthItem(
                "download_client", "warning", "No enabled download client: nothing can be grabbed"
            )
        ]

    async def check(row: DownloadClient) -> list[HealthItem]:
        client = build_client(
            DownloadClientImplementation(row.implementation), row.settings, runtime.http
        )
        try:
            outcome = await asyncio.wait_for(client.test(), CLIENT_TIMEOUT)
        except (DownloadClientError, TimeoutError) as exc:
            reason = str(exc) or "timed out"
            return [HealthItem("download_client", "error", f"{row.name}: {reason}")]
        return [
            HealthItem("download_client", "warning", f"{row.name}: {w}") for w in outcome.warnings
        ]

    results = await asyncio.gather(*(check(c) for c in clients))
    return [item for result in results for item in result]


def _imports(session: Session) -> list[HealthItem]:
    items = []
    blocked = session.scalar(
        select(func.count(Download.id)).where(
            Download.status == DownloadStatus.IMPORT_BLOCKED.value
        )
    )
    if blocked:
        items.append(
            HealthItem(
                "import",
                "warning",
                f"{blocked} download(s) couldn't be imported: see Activity → Queue",
            )
        )
    unseen = session.scalar(
        select(func.count(Download.id)).where(
            Download.status == DownloadStatus.PENDING_IMPORT.value,
            Download.message.like("Magarr can't see%"),
        )
    )
    if unseen:
        items.append(
            HealthItem(
                "import",
                "warning",
                f"{unseen} finished download(s) are in a folder Magarr can't see: "
                "add a remote path mapping",
            )
        )
    return items


def _notifications(session: Session) -> list[HealthItem]:
    failing = session.scalars(
        select(Notification).where(
            Notification.enabled.is_(True), Notification.last_error.is_not(None)
        )
    )
    return [
        HealthItem("notification", "warning", f"Notification {n.name} is failing: {n.last_error}")
        for n in failing
    ]


def _automation(session: Session) -> list[HealthItem]:
    if get_automation_settings(session).monitoring_enabled:
        return []
    return [
        HealthItem("automation", "notice", "Automatic searching is paused (Settings → Automation)")
    ]


async def check_health(session: Session, runtime: IndexerRuntime) -> HealthReport:
    items = [
        *_root_folders(session),
        *_indexers(session),
        *await _download_clients(session, runtime),
        *_imports(session),
        *_notifications(session),
        *_automation(session),
    ]
    session.commit()
    order = {"error": 0, "warning": 1, "notice": 2}
    items.sort(key=lambda i: order[i.level])
    return HealthReport(checked_at=datetime.now(UTC), items=items)
