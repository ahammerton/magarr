from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import Field
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.paging import PagingDep
from magarr.api.schemas import ApiModel
from magarr.domain import issue_service
from magarr.domain.enums import ACTIVE_DOWNLOAD_STATUSES, DownloadStatus, IssueStatus, Protocol
from magarr.domain.issue_service import IssueFields
from magarr.domain.magazines import get_magazine
from magarr.domain.models import Download, Issue, IssueFile
from magarr.pipeline.search import EvaluatedRelease, search_issue

router = APIRouter(prefix="/api/v1/issue", tags=["Issues"])


class FileResource(ApiModel):
    id: int
    relative_path: str
    size: int
    format: str
    quality: str
    edition: str | None
    date_added: datetime

    @classmethod
    def of(cls, file: IssueFile) -> "FileResource":
        return cls(
            id=file.id,
            relative_path=file.relative_path,
            size=file.size,
            format=file.format,
            quality=file.quality,
            edition=file.edition,
            date_added=file.date_added,
        )


class IssueResource(ApiModel):
    id: int
    magazine_id: int
    issue_number: str
    sort_index: float
    title: str | None
    publish_date: date | None
    cover_url: str | None
    monitored: bool
    status: IssueStatus
    # Last automatic (backlog or wanted-page) search.
    last_searched_at: datetime | None = None
    file: FileResource | None
    # The issue's current download (in a client, or finished and waiting for import).
    download: "IssueDownload | None" = None

    @classmethod
    def of(cls, issue: Issue, download: Download | None = None) -> "IssueResource":
        return cls(
            id=issue.id,
            magazine_id=issue.magazine_id,
            issue_number=issue.issue_number,
            sort_index=issue.sort_index,
            title=issue.title,
            publish_date=issue.publish_date,
            cover_url=issue.cover_url,
            monitored=issue.monitored,
            status=IssueStatus(issue.status),
            last_searched_at=issue.last_searched_at,
            file=FileResource.of(issue.file) if issue.file else None,
            download=IssueDownload.of(download) if download else None,
        )


class IssueDownload(ApiModel):
    id: int
    status: DownloadStatus
    progress: float
    title: str
    message: str | None

    @classmethod
    def of(cls, d: Download) -> "IssueDownload":
        return cls(
            id=d.id,
            status=DownloadStatus(d.status),
            progress=d.progress,
            title=d.title,
            message=d.message,
        )


IssueResource.model_rebuild()


def current_downloads(session, issue_ids: list[int]) -> dict[int, Download]:
    """Latest active or pending-import download per issue, in one query."""
    if not issue_ids:
        return {}
    wanted = [s.value for s in ACTIVE_DOWNLOAD_STATUSES] + [DownloadStatus.PENDING_IMPORT.value]
    rows = session.scalars(
        select(Download)
        .where(Download.issue_id.in_(issue_ids), Download.status.in_(wanted))
        .order_by(Download.id)
    )
    return {d.issue_id: d for d in rows}  # later ids overwrite earlier: latest wins


class _IssueBody(ApiModel):
    title: str | None = Field(default=None, max_length=255)
    publish_date: date | None = None
    cover_url: str | None = Field(default=None, max_length=2048)
    monitored: bool | None = None
    status: IssueStatus | None = None
    sort_index: float | None = None

    def fields(self) -> IssueFields:
        return IssueFields(**self.model_dump(), provided=set(self.model_fields_set))


class IssueCreate(_IssueBody):
    magazine_id: int
    issue_number: str = Field(min_length=1, max_length=100)

    def fields(self) -> IssueFields:
        data = self.model_dump(exclude={"magazine_id"})
        return IssueFields(**data, provided=set(self.model_fields_set) - {"magazine_id"})


class IssueUpdate(_IssueBody):
    issue_number: str | None = Field(default=None, min_length=1, max_length=100)


class IssueBulkUpdate(ApiModel):
    ids: list[int] = Field(min_length=1, max_length=10_000)
    monitored: bool | None = None
    status: IssueStatus | None = None


class ParsedRelease(ApiModel):
    magazine_title: str
    issue_number: str | None
    year: int | None
    month: int | None
    format: str | None
    quality: str
    edition: str | None
    group: str | None
    is_pack: bool
    language: str | None


class ReleaseResource(ApiModel):
    # No download URL: indexer and Prowlarr links embed their API key, so they stay server-side.
    guid: str
    title: str
    indexer_id: int | None
    indexer: str
    protocol: Protocol
    info_url: str | None
    size: int
    publish_date: datetime | None
    age_days: int | None
    seeders: int | None
    leechers: int | None
    grabs: int | None
    categories: list[int]
    parsed: ParsedRelease
    rejected: bool
    rejection_reasons: list[str]

    @classmethod
    def of(cls, item: EvaluatedRelease) -> "ReleaseResource":
        r, p = item.release, item.parsed
        return cls(
            guid=r.guid,
            title=r.title,
            indexer_id=r.indexer_id,
            indexer=r.indexer,
            protocol=r.protocol,
            info_url=r.info_url,
            size=r.size,
            publish_date=r.publish_date,
            age_days=r.age_days,
            seeders=r.seeders,
            leechers=r.leechers,
            grabs=r.grabs,
            categories=list(r.categories),
            parsed=ParsedRelease(
                magazine_title=p.title,
                issue_number=p.issue_key,
                year=p.year,
                month=p.month,
                format=p.format.value if p.format else None,
                quality=p.quality,
                edition=p.edition,
                group=p.group,
                is_pack=p.is_pack,
                language=p.language,
            ),
            rejected=not item.approved,
            rejection_reasons=item.rejections,
        )


class IndexerOutcomeResource(ApiModel):
    indexer_id: int
    name: str
    ok: bool
    release_count: int
    error: str | None
    skipped_until: datetime | None


class SearchResult(ApiModel):
    queries: list[str]
    indexers: list[IndexerOutcomeResource]
    releases: list[ReleaseResource]


@router.get("", response_model=list[IssueResource])
def list_issues(
    magazine_id: Annotated[int, Query(alias="magazineId")],
    session: SessionDep,
    paging: PagingDep,
    response: Response,
) -> list[IssueResource]:
    get_magazine(session, magazine_id)
    stmt = select(Issue).where(Issue.magazine_id == magazine_id).order_by(Issue.sort_index.desc())
    rows = list(session.scalars(paging.apply(session, stmt, response)))
    downloads = current_downloads(session, [i.id for i in rows])
    return [IssueResource.of(i, downloads.get(i.id)) for i in rows]


@router.post("", response_model=IssueResource, status_code=status.HTTP_201_CREATED)
def create_issue(body: IssueCreate, session: SessionDep) -> IssueResource:
    issue = issue_service.create_issue(session, body.magazine_id, body.fields())
    session.commit()
    return IssueResource.of(issue)


@router.post("/bulk", response_model=list[IssueResource])
def bulk_update(body: IssueBulkUpdate, session: SessionDep) -> list[IssueResource]:
    issues = issue_service.bulk_update(session, body.ids, body.monitored, body.status)
    session.commit()
    return [IssueResource.of(i) for i in issues]


@router.get("/{issue_id}", response_model=IssueResource)
def get_issue(issue_id: int, session: SessionDep) -> IssueResource:
    issue = issue_service.get_issue(session, issue_id)
    return IssueResource.of(issue, current_downloads(session, [issue.id]).get(issue.id))


@router.patch("/{issue_id}", response_model=IssueResource)
def update_issue(issue_id: int, body: IssueUpdate, session: SessionDep) -> IssueResource:
    issue = issue_service.update_issue(session, issue_id, body.fields())
    session.commit()
    return IssueResource.of(issue)


@router.delete("/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_issue(issue_id: int, session: SessionDep) -> None:
    """Deletes the issue record. The file on disk is not touched."""
    issue_service.delete_issue(session, issue_id)
    session.commit()


@router.post("/{issue_id}/search", response_model=SearchResult)
async def search(issue_id: int, request: Request, session: SessionDep) -> SearchResult:
    """Interactive search across every enabled indexer that applies to the magazine."""
    issue = issue_service.get_issue(session, issue_id)
    result = await search_issue(session, request.app.state.indexer_runtime, issue)
    session.commit()  # indexer health changes
    return SearchResult(
        queries=result.queries,
        indexers=[
            IndexerOutcomeResource(
                indexer_id=o.indexer_id,
                name=o.name,
                ok=o.ok,
                release_count=o.release_count,
                error=o.error,
                skipped_until=o.skipped_until,
            )
            for o in result.indexers
        ],
        releases=[ReleaseResource.of(r) for r in result.releases],
    )
