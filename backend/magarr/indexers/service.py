"""Indexer CRUD and connection tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.core.netguard import check_configured_url
from magarr.domain.enums import IndexerImplementation, IndexerSource
from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.models import Indexer
from magarr.indexers.caps import Caps
from magarr.indexers.categories import DEFAULT_CATEGORIES
from magarr.indexers.client import IndexerEndpoint, NewznabClient
from magarr.indexers.runtime import IndexerRuntime

MASKED_KEY = "********"


@dataclass
class IndexerFields:
    """Writable indexer fields. On update, only names in ``provided`` are applied."""

    name: str | None = None
    implementation: IndexerImplementation | None = None
    base_url: str | None = None
    api_path: str | None = None
    api_key: str | None = None
    categories: list[int] | None = None
    priority: int | None = None
    enabled: bool | None = None
    tags: list[str] | None = None
    request_interval: float | None = None
    provided: set[str] = field(default_factory=set)


def normalize_url(raw: str) -> str:
    url = raw.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise DomainError("URL must start with http:// or https://")
    check_configured_url(url)
    return url.rstrip("/") + "/"


def endpoint_for(indexer: Indexer) -> IndexerEndpoint:
    return IndexerEndpoint(
        id=indexer.id,
        name=indexer.name,
        implementation=IndexerImplementation(indexer.implementation),
        base_url=indexer.base_url,
        api_path=indexer.api_path,
        api_key=indexer.api_key,
        categories=tuple(indexer.categories or DEFAULT_CATEGORIES),
        request_interval=indexer.request_interval,
    )


def get_indexer(session: Session, indexer_id: int) -> Indexer:
    indexer = session.get(Indexer, indexer_id)
    if indexer is None:
        raise NotFoundError(f"Indexer {indexer_id} not found")
    return indexer


def _check_name(session: Session, name: str, exclude_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise DomainError("Name cannot be empty")
    stmt = select(Indexer.id).where(func.lower(Indexer.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Indexer.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"An indexer named '{name}' already exists")
    return name


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    if "base_url" in values:
        values["base_url"] = normalize_url(values["base_url"] or "")
    if "api_path" in values:
        values["api_path"] = "/" + (values["api_path"] or "/api").strip().lstrip("/")
    if "api_key" in values:
        values["api_key"] = (values["api_key"] or "").strip()
    if "categories" in values:
        cats = sorted({int(c) for c in values["categories"] or []})
        if any(c <= 0 for c in cats):
            raise DomainError("Categories must be positive Newznab category ids")
        values["categories"] = cats or list(DEFAULT_CATEGORIES)
    if "priority" in values and not 1 <= (values["priority"] or 0) <= 50:
        raise DomainError("Priority must be between 1 and 50")
    if "request_interval" in values and not 0 <= (values["request_interval"] or 0) <= 60:
        raise DomainError("Request interval must be between 0 and 60 seconds")
    if "tags" in values:
        seen: dict[str, str] = {}
        for tag in values["tags"] or []:
            if tag.strip():
                seen.setdefault(tag.strip().casefold(), tag.strip())
        values["tags"] = list(seen.values())
    if "implementation" in values and values["implementation"] is not None:
        values["implementation"] = values["implementation"].value
    return values


def create_indexer(session: Session, fields: IndexerFields) -> Indexer:
    if not fields.base_url:
        raise DomainError("URL is required")
    values = _clean(
        {
            "name": fields.name,
            "implementation": fields.implementation or IndexerImplementation.NEWZNAB,
            "base_url": fields.base_url,
            "api_path": fields.api_path or "/api",
            "api_key": fields.api_key or "",
            "categories": fields.categories or [],
            "priority": 25 if fields.priority is None else fields.priority,
            "enabled": True if fields.enabled is None else fields.enabled,
            "tags": fields.tags or [],
            "request_interval": 2.0 if fields.request_interval is None else fields.request_interval,
        }
    )
    values["name"] = _check_name(session, fields.name or "")
    indexer = Indexer(**values, source=IndexerSource.MANUAL.value)
    session.add(indexer)
    session.flush()
    return indexer


def update_indexer(session: Session, indexer_id: int, fields: IndexerFields) -> Indexer:
    indexer = get_indexer(session, indexer_id)
    values = {name: getattr(fields, name) for name in fields.provided}
    if values.get("api_key") == MASKED_KEY:
        del values["api_key"]  # the UI echoes the mask back when the key is unchanged
    for name in ("implementation", "base_url", "enabled", "priority"):
        if name in values and values[name] is None:
            raise DomainError(f"{name} cannot be null")
    values = _clean(values)
    if "name" in values:
        values["name"] = _check_name(session, values["name"] or "", exclude_id=indexer.id)
    for name, value in values.items():
        setattr(indexer, name, value)
    session.flush()
    return indexer


def delete_indexer(session: Session, indexer_id: int) -> None:
    session.delete(get_indexer(session, indexer_id))
    session.flush()


def unsaved_endpoint(fields: IndexerFields, existing: Indexer | None = None) -> IndexerEndpoint:
    """Endpoint for testing settings before they are saved."""
    api_key = fields.api_key
    if (api_key is None or api_key == MASKED_KEY) and existing is not None:
        api_key = existing.api_key
    return IndexerEndpoint(
        id=existing.id if existing else None,
        name=fields.name or (existing.name if existing else "Test"),
        implementation=fields.implementation or IndexerImplementation.NEWZNAB,
        base_url=normalize_url(fields.base_url or ""),
        api_path="/" + (fields.api_path or "/api").lstrip("/"),
        api_key=(api_key or "").strip(),
        categories=tuple(fields.categories or DEFAULT_CATEGORIES),
        request_interval=0,
    )


async def test_endpoint(endpoint: IndexerEndpoint, runtime: IndexerRuntime) -> Caps:
    """Fetch caps and run one tiny search so bad keys fail here, not at search time."""
    client = NewznabClient(endpoint, runtime)
    caps = await client.caps()
    if caps.search_available:
        await client.search("magazine", limit=1, max_pages=1)
    return caps
