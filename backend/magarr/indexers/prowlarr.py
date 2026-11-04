"""Consume indexers already configured in Prowlarr (Prowlarr stays the source of truth).

Each Prowlarr indexer is exposed as a Newznab/Torznab feed at ``<prowlarr>/<id>/api`` using
Prowlarr's own API key, so Magarr stores it as a regular indexer with ``source=prowlarr``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.domain.enums import IndexerImplementation, IndexerSource, Protocol
from magarr.domain.errors import DomainError
from magarr.domain.models import Indexer, ProwlarrConfig
from magarr.indexers.categories import default_categories_for, is_book_category
from magarr.indexers.client import IndexerRequestError
from magarr.indexers.runtime import IndexerRuntime
from magarr.indexers.service import normalize_url

logger = logging.getLogger(__name__)

NAME_SUFFIX = " (Prowlarr)"


@dataclass(frozen=True)
class ProwlarrIndexer:
    id: int
    name: str
    protocol: Protocol
    enabled: bool
    priority: int
    categories: set[int]


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (name, reason)


def get_config(session: Session) -> ProwlarrConfig:
    config = session.scalar(select(ProwlarrConfig).order_by(ProwlarrConfig.id).limit(1))
    if config is None:
        config = ProwlarrConfig(url="", api_key="")
        session.add(config)
        session.flush()
    return config


def _categories(raw: Any) -> set[int]:
    ids: set[int] = set()
    for category in raw or []:
        if isinstance(category.get("id"), int):
            ids.add(category["id"])
        ids |= _categories(category.get("subCategories"))
    return ids


def parse_indexers(payload: Any) -> list[ProwlarrIndexer]:
    if not isinstance(payload, list):
        raise DomainError("Unexpected response from Prowlarr's /api/v1/indexer")
    indexers = []
    for item in payload:
        try:
            protocol = Protocol(item["protocol"])
        except (KeyError, ValueError):
            continue  # unknown protocol: nothing Magarr can use
        indexers.append(
            ProwlarrIndexer(
                id=int(item["id"]),
                name=str(item.get("name") or f"Indexer {item['id']}"),
                protocol=protocol,
                enabled=bool(item.get("enable", True)),
                priority=int(item.get("priority") or 25),
                categories=_categories((item.get("capabilities") or {}).get("categories")),
            )
        )
    return indexers


async def _get_json(runtime: IndexerRuntime, url: str, api_key: str, path: str) -> Any:
    try:
        response = await runtime.http.get(
            url.rstrip("/") + path, headers={"X-Api-Key": api_key, "Accept": "application/json"}
        )
    except httpx.HTTPError as exc:
        raise IndexerRequestError(f"Could not reach Prowlarr: {exc}") from exc
    if response.status_code == 401:
        raise IndexerRequestError("Prowlarr rejected the API key")
    if response.status_code >= 400:
        raise IndexerRequestError(f"Prowlarr returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise IndexerRequestError("Prowlarr did not return JSON; check the URL") from exc


async def test_connection(runtime: IndexerRuntime, url: str, api_key: str) -> str:
    """Returns Prowlarr's version."""
    status = await _get_json(runtime, normalize_url(url), api_key, "/api/v1/system/status")
    if not isinstance(status, dict) or "version" not in status:
        raise IndexerRequestError("That URL does not look like Prowlarr")
    return str(status["version"])


async def fetch_indexers(runtime: IndexerRuntime, url: str, api_key: str) -> list[ProwlarrIndexer]:
    return parse_indexers(await _get_json(runtime, normalize_url(url), api_key, "/api/v1/indexer"))


def _unique_name(session: Session, wanted: str, exclude_id: int | None) -> str:
    name, n = wanted, 2
    while True:
        stmt = select(Indexer.id).where(func.lower(Indexer.name) == name.lower())
        if exclude_id is not None:
            stmt = stmt.where(Indexer.id != exclude_id)
        if session.scalar(stmt) is None:
            return name
        name, n = f"{wanted} {n}", n + 1


def apply_sync(
    session: Session, config: ProwlarrConfig, remote: list[ProwlarrIndexer]
) -> SyncResult:
    result = SyncResult()
    base = normalize_url(config.url)
    existing = {
        i.prowlarr_id: i
        for i in session.scalars(
            select(Indexer).where(Indexer.source == IndexerSource.PROWLARR.value)
        )
    }
    keep: set[int] = set()

    for item in remote:
        if not item.enabled:
            result.skipped.append((item.name, "Disabled in Prowlarr"))
            continue
        book_categories = {c for c in item.categories if is_book_category(c)}
        if not book_categories:
            result.skipped.append((item.name, "No book or magazine categories"))
            continue
        keep.add(item.id)
        implementation = (
            IndexerImplementation.NEWZNAB
            if item.protocol is Protocol.USENET
            else IndexerImplementation.TORZNAB
        )
        values = {
            "implementation": implementation.value,
            "base_url": f"{base}{item.id}/",
            "api_path": "/api",
            "api_key": config.api_key,
            "priority": max(1, min(item.priority, 50)),
        }
        indexer = existing.get(item.id)
        if indexer is None:
            indexer = Indexer(
                name=_unique_name(session, item.name + NAME_SUFFIX, None),
                categories=default_categories_for(book_categories),
                enabled=True,
                tags=[],
                request_interval=2.0,
                source=IndexerSource.PROWLARR.value,
                prowlarr_id=item.id,
                **values,
            )
            session.add(indexer)
            session.flush()
            result.added.append(indexer.name)
        else:
            # Connection details follow Prowlarr; categories, tags and enabled stay the user's.
            changed = any(getattr(indexer, k) != v for k, v in values.items())
            name = _unique_name(session, item.name + NAME_SUFFIX, indexer.id)
            changed = changed or indexer.name != name
            for key, value in values.items():
                setattr(indexer, key, value)
            indexer.name = name
            if changed:
                result.updated.append(indexer.name)

    for prowlarr_id, indexer in existing.items():
        if prowlarr_id not in keep:
            result.removed.append(indexer.name)
            session.delete(indexer)

    config.last_sync = datetime.now(UTC)
    session.flush()
    logger.info("Prowlarr sync finished", extra={k: len(v) for k, v in vars(result).items()})
    return result
