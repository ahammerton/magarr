"""Send a release to a download client and start tracking it."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from magarr.core.logging import redact
from magarr.core.netguard import Address, check_fetched_url, trusted_addresses
from magarr.domain.download_clients import client_for
from magarr.domain.enums import (
    DownloadClientImplementation,
    DownloadStatus,
    HistoryEventType,
    Protocol,
)
from magarr.domain.errors import DomainError
from magarr.domain.history import record
from magarr.domain.models import Download, Indexer, Issue
from magarr.downloaders.base import DownloadClientError, GrabPayload
from magarr.downloaders.registry import build_client
from magarr.indexers.client import IndexerRelease
from magarr.indexers.runtime import IndexerRuntime

logger = logging.getLogger(__name__)

MAX_RELEASE_BYTES = 20 * 1024 * 1024  # NZBs and .torrent files are small; refuse anything huge


class GrabError(DomainError):
    status_code = 502


def release_snapshot(release: IndexerRelease) -> dict:
    """Release as stored with the download and in history. No download URL: it embeds keys."""
    data = asdict(release)
    data.pop("download_url", None)
    data["protocol"] = release.protocol.value
    data["publish_date"] = release.publish_date.isoformat() if release.publish_date else None
    data["categories"] = list(release.categories)
    return data


async def fetch_payload(
    runtime: IndexerRuntime, release: IndexerRelease, trusted: set[Address] | None = None
) -> GrabPayload:
    """Download the NZB/.torrent ourselves (validating it), or resolve a magnet redirect.

    The link and every redirect must point at the public internet or at the indexer itself
    (``trusted``): see magarr.core.netguard."""
    filename = "".join(c if c.isalnum() or c in "._- " else "_" for c in release.title)[:180]
    if release.download_url.startswith("magnet:"):
        return GrabPayload(title=release.title, filename=filename, magnet=release.download_url)
    url = release.download_url
    try:
        for _ in range(5):
            await check_fetched_url(url, trusted or set())
            response = await runtime.http.get(url, follow_redirects=False)
            if response.is_redirect:
                location = response.headers.get("location", "")
                if location.startswith("magnet:"):
                    return GrabPayload(title=release.title, filename=filename, magnet=location)
                url = urljoin(url, location)
                continue
            break
        else:
            raise GrabError("Too many redirects fetching the release")
    except httpx.HTTPError as exc:
        raise GrabError(
            f"Could not fetch the release from {release.indexer}: {redact(str(exc))}"
        ) from exc
    if response.status_code >= 400:
        raise GrabError(f"{release.indexer} returned HTTP {response.status_code} for the release")
    content = response.content
    if len(content) > MAX_RELEASE_BYTES:
        raise GrabError("The release file is unexpectedly large; refusing it")
    if release.protocol is Protocol.USENET:
        if b"<nzb" not in content[:4096].lower():
            raise GrabError(f"{release.indexer} did not return an NZB (daily grab limit reached?)")
        return GrabPayload(title=release.title, filename=f"{filename}.nzb", content=content)
    if not content.startswith(b"d"):
        raise GrabError(f"{release.indexer} did not return a .torrent file")
    return GrabPayload(title=release.title, filename=f"{filename}.torrent", content=content)


async def grab_release(
    session: Session, runtime: IndexerRuntime, issue: Issue, release: IndexerRelease, *, source: str
) -> Download:
    """Fetch, send to the best client for the protocol, and record. Caller holds the issue lock."""
    row = client_for(session, release.protocol)
    if row is None:
        raise DomainError(f"No enabled download client for {release.protocol.value} releases")
    client = build_client(
        DownloadClientImplementation(row.implementation), row.settings, runtime.http
    )
    indexer = session.get(Indexer, release.indexer_id) if release.indexer_id is not None else None
    trusted = await trusted_addresses(indexer.base_url) if indexer else set()
    payload = await fetch_payload(runtime, release, trusted)
    try:
        external_id = await client.add(payload)
    except DownloadClientError as exc:
        raise GrabError(f"{row.name}: {exc}") from exc

    download = Download(
        issue_id=issue.id,
        download_client_id=row.id,
        external_id=external_id,
        title=release.title,
        protocol=release.protocol.value,
        release=release_snapshot(release),
        status=DownloadStatus.QUEUED.value,
        size=release.size,
        size_left=release.size,
    )
    session.add(download)
    session.flush()
    record(
        session,
        HistoryEventType.GRABBED,
        release.title,
        issue,
        download_id=download.id,
        client=row.name,
        source=source,
        release=download.release,
        at=datetime.now().astimezone().isoformat(),
    )
    session.flush()
    logger.info(
        "Grabbed release",
        extra={
            "release": release.title,
            "issue_id": issue.id,
            "client": row.name,
            "source": source,
        },
    )
    return download
