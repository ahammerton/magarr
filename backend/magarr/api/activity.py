"""Grab, queue, history and blocklist."""

import asyncio
import contextlib
import secrets
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from pydantic import Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from magarr.api.deps import SessionDep
from magarr.api.paging import PagingDep
from magarr.api.schemas import ApiModel
from magarr.domain.enums import (
    ACTIVE_DOWNLOAD_STATUSES,
    DownloadClientImplementation,
    DownloadStatus,
    HistoryEventType,
    Protocol,
)
from magarr.domain.errors import DomainError, NotFoundError
from magarr.domain.issue_service import get_issue
from magarr.domain.models import BlocklistItem, Download, HistoryEvent, Issue
from magarr.downloaders.base import DownloadClientError
from magarr.downloaders.registry import build_client
from magarr.importers.importer import import_download
from magarr.indexers.client import IndexerRelease
from magarr.pipeline.grab import grab_release

router = APIRouter(prefix="/api/v1", tags=["Activity"])


class GrabBody(ApiModel):
    guid: str = Field(max_length=2048)
    indexer_id: int | None
    issue_id: int


class DownloadResource(ApiModel):
    id: int
    issue_id: int | None
    magazine_id: int | None
    magazine_title: str | None
    issue_number: str | None
    download_client_id: int | None
    title: str
    protocol: Protocol
    status: DownloadStatus
    progress: float
    size: int
    size_left: int
    output_path: str | None
    message: str | None
    added: datetime
    completed_at: datetime | None

    @classmethod
    def of(cls, d: Download) -> "DownloadResource":
        return cls(
            id=d.id,
            issue_id=d.issue_id,
            magazine_id=d.issue.magazine_id if d.issue else None,
            magazine_title=d.issue.magazine.title if d.issue else None,
            issue_number=d.issue.issue_number if d.issue else None,
            download_client_id=d.download_client_id,
            title=d.title,
            protocol=Protocol(d.protocol),
            status=DownloadStatus(d.status),
            progress=d.progress,
            size=d.size,
            size_left=d.size_left,
            output_path=d.output_path,
            message=d.message,
            added=d.created_at,
            completed_at=d.completed_at,
        )


class HistoryResource(ApiModel):
    id: int
    event_type: HistoryEventType
    issue_id: int | None
    magazine_id: int | None
    magazine_title: str | None
    issue_number: str | None
    download_id: int | None
    source_title: str
    data: dict[str, Any]
    date: datetime


class HistoryPage(ApiModel):
    total: int
    page: int
    page_size: int
    records: list[HistoryResource]


class BlocklistResource(ApiModel):
    id: int
    issue_id: int | None
    magazine_id: int | None
    source_title: str
    protocol: Protocol
    reason: str | None
    date: datetime


@router.post("/release/grab", response_model=DownloadResource, status_code=status.HTTP_201_CREATED)
async def grab(body: GrabBody, request: Request, session: SessionDep) -> DownloadResource:
    """Grab a release from a recent search, referenced by (indexer, guid).

    Releases are cached server-side because download URLs embed indexer keys and are never sent
    to the browser. Manual grabs bypass the decision engine on purpose (the user chose it).
    """
    runtime = request.app.state.indexer_runtime
    issue = get_issue(session, body.issue_id)
    release = runtime.releases.get(body.indexer_id, body.guid)
    if not isinstance(release, IndexerRelease):
        raise DomainError(
            "That release is no longer cached; search again and grab it from the new results"
        )
    async with runtime.issue_lock(issue.id):
        download = await grab_release(session, runtime, issue, release, source="manual grab")
        session.commit()
    request.app.state.events.publish("queue")
    return DownloadResource.of(download)


QUEUE_STATUSES = [s.value for s in ACTIVE_DOWNLOAD_STATUSES] + [
    DownloadStatus.PENDING_IMPORT.value,
    DownloadStatus.IMPORT_BLOCKED.value,
]


def queue_query() -> Select[tuple[Download]]:
    return (
        select(Download)
        .where(Download.status.in_(QUEUE_STATUSES))
        .options(selectinload(Download.issue).selectinload(Issue.magazine))
        .order_by(Download.id)
    )


def queue_items(session) -> list[DownloadResource]:
    return [DownloadResource.of(d) for d in session.scalars(queue_query())]


@router.get("/queue", response_model=list[DownloadResource])
def queue(session: SessionDep, paging: PagingDep, response: Response) -> list[DownloadResource]:
    """Downloads in a client, waiting for import, or needing attention to import."""
    rows = session.scalars(paging.apply(session, queue_query(), response))
    return [DownloadResource.of(d) for d in rows]


def _get_download(session, download_id: int) -> Download:
    download = session.get(Download, download_id)
    if download is None:
        raise NotFoundError(f"Download {download_id} not found")
    return download


@router.post("/queue/{download_id}/import", response_model=DownloadResource)
def retry_import(download_id: int, request: Request, session: SessionDep) -> DownloadResource:
    """Try the automatic import again (e.g. after adding a path mapping)."""
    download = _get_download(session, download_id)
    if download.status not in (
        DownloadStatus.PENDING_IMPORT.value,
        DownloadStatus.IMPORT_BLOCKED.value,
    ):
        raise DomainError("Only finished downloads waiting for import can be imported")
    import_download(session, download)
    session.commit()
    request.app.state.events.publish("queue")
    return DownloadResource.of(download)


@router.delete("/queue/{download_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_queue(
    download_id: int,
    request: Request,
    session: SessionDep,
    remove_from_client: Annotated[bool, Query(alias="removeFromClient")] = True,
    blocklist: bool = False,
) -> None:
    """Stop tracking a download; optionally delete it in the client and blocklist the release."""
    download = _get_download(session, download_id)
    row = download.download_client
    if remove_from_client and row is not None:
        client = build_client(
            DownloadClientImplementation(row.implementation),
            row.settings,
            request.app.state.indexer_runtime.http,
        )
        try:
            await client.remove(download.external_id, delete_data=True)
        except DownloadClientError as exc:
            raise DomainError(f"{row.name}: {exc}") from exc
    if blocklist:
        session.add(
            BlocklistItem(
                issue_id=download.issue_id,
                magazine_id=download.issue.magazine_id if download.issue else None,
                guid=download.release.get("guid", ""),
                indexer_id=download.release.get("indexer_id"),
                source_title=download.title,
                protocol=download.protocol,
                reason="Removed from the queue by the user",
            )
        )
    download.status = DownloadStatus.FAILED.value
    download.message = "Removed from the queue"
    session.commit()
    request.app.state.events.publish("queue")


@router.websocket("/ws/queue")
async def queue_socket(websocket: WebSocket) -> None:
    """Live queue: a snapshot on connect and whenever downloads change (heartbeat every 30 s).
    Auth: ?apikey= (browsers can't send headers on WebSocket upgrades)."""
    settings = websocket.app.state.settings
    supplied = websocket.query_params.get("apikey", "")
    if not supplied or not secrets.compare_digest(supplied, settings.auth.api_key):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    factory = websocket.app.state.session_factory

    def snapshot() -> list[dict]:
        with factory() as session:
            return [d.model_dump(mode="json", by_alias=True) for d in queue_items(session)]

    async with websocket.app.state.events.subscribe() as changes:
        try:
            while True:
                await websocket.send_json({"type": "queue", "queue": snapshot()})
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(changes.get(), timeout=30)
        except (WebSocketDisconnect, RuntimeError):
            return


@router.get("/history", response_model=HistoryPage)
def history(
    session: SessionDep,
    issue_id: Annotated[int | None, Query(alias="issueId")] = None,
    magazine_id: Annotated[int | None, Query(alias="magazineId")] = None,
    event_type: Annotated[HistoryEventType | None, Query(alias="eventType")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=500)] = 50,
) -> HistoryPage:
    stmt = select(HistoryEvent)
    if issue_id is not None:
        stmt = stmt.where(HistoryEvent.issue_id == issue_id)
    if magazine_id is not None:
        stmt = stmt.where(HistoryEvent.magazine_id == magazine_id)
    if event_type is not None:
        stmt = stmt.where(HistoryEvent.event_type == event_type.value)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        session.scalars(
            stmt.order_by(HistoryEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    )
    ids = {h.issue_id for h in rows if h.issue_id is not None}
    issues = (
        {
            i.id: i
            for i in session.scalars(
                select(Issue).where(Issue.id.in_(ids)).options(selectinload(Issue.magazine))
            )
        }
        if ids
        else {}
    )
    return HistoryPage(
        total=total,
        page=page,
        page_size=page_size,
        records=[
            HistoryResource(
                id=h.id,
                event_type=HistoryEventType(h.event_type),
                issue_id=h.issue_id,
                magazine_id=h.magazine_id,
                magazine_title=issues[h.issue_id].magazine.title if h.issue_id in issues else None,
                issue_number=issues[h.issue_id].issue_number if h.issue_id in issues else None,
                download_id=h.download_id,
                source_title=h.source_title,
                data=h.data,
                date=h.created_at,
            )
            for h in rows
        ],
    )


@router.get("/blocklist", response_model=list[BlocklistResource])
def blocklist(
    session: SessionDep, paging: PagingDep, response: Response
) -> list[BlocklistResource]:
    stmt = select(BlocklistItem).order_by(BlocklistItem.id.desc())
    rows = session.scalars(paging.apply(session, stmt, response))
    return [
        BlocklistResource(
            id=b.id,
            issue_id=b.issue_id,
            magazine_id=b.magazine_id,
            source_title=b.source_title,
            protocol=Protocol(b.protocol),
            reason=b.reason,
            date=b.created_at,
        )
        for b in rows
    ]


@router.delete("/blocklist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def unblock(item_id: int, session: SessionDep) -> None:
    item = session.get(BlocklistItem, item_id)
    if item is None:
        raise NotFoundError(f"Blocklist item {item_id} not found")
    session.delete(item)
    session.commit()
