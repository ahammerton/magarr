from datetime import date, datetime

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.issues import IssueResource
from magarr.api.paging import PagingDep
from magarr.api.schemas import ApiModel, ShortText, Tag
from magarr.domain import magazines
from magarr.domain.covers import magazine_cover
from magarr.domain.enums import Frequency
from magarr.domain.errors import NotFoundError
from magarr.domain.magazines import MagazineFields, MagazineStats
from magarr.domain.models import Magazine
from magarr.importers.csv_import import import_csv

router = APIRouter(prefix="/api/v1/magazine", tags=["Magazines"])


class MagazineStatistics(ApiModel):
    issue_count: int
    downloaded_count: int
    wanted_count: int
    size_on_disk: int


class MagazineResource(ApiModel):
    id: int
    title: str
    sort_title: str
    alternate_titles: list[str]
    publisher: str | None
    language: str
    category: str | None
    frequency: Frequency
    first_issue_year: int | None
    tags: list[str]
    quality_profile_id: int
    root_folder_id: int
    folder: str
    path: str
    monitored: bool
    poster_url: str | None
    # Automatic searches skip issues published before this date.
    search_cutoff: date | None
    # RSS sync adds and grabs specials it sees (e.g. "Christmas Special 2026").
    grab_new_specials: bool
    # Cover of the earliest downloaded issue; the UI shows it when no poster URL is set.
    cover_url: str | None
    issue_naming_template: str | None
    notes: str | None
    added: datetime
    statistics: MagazineStatistics

    @classmethod
    def of(cls, magazine: Magazine, stats: MagazineStats | None) -> "MagazineResource":
        stats = stats or MagazineStats()
        return cls(
            id=magazine.id,
            title=magazine.title,
            sort_title=magazine.sort_title,
            alternate_titles=magazine.alternate_titles or [],
            publisher=magazine.publisher,
            language=magazine.language,
            category=magazine.category,
            frequency=Frequency(magazine.frequency),
            first_issue_year=magazine.first_issue_year,
            tags=magazine.tags or [],
            quality_profile_id=magazine.quality_profile_id,
            root_folder_id=magazine.root_folder_id,
            folder=magazine.folder,
            path=str(magazine.path),
            monitored=magazine.monitored,
            poster_url=magazine.poster_url,
            search_cutoff=magazine.search_cutoff,
            grab_new_specials=magazine.grab_new_specials,
            cover_url=(
                # The query string only changes the URL when the files change, for the UI cache.
                f"/api/v1/magazine/{magazine.id}/cover?v={stats.downloaded_count}-{stats.size_on_disk}"
                if stats.downloaded_count
                else None
            ),
            issue_naming_template=magazine.issue_naming_template,
            notes=magazine.notes,
            added=magazine.created_at,
            statistics=MagazineStatistics(
                issue_count=stats.issue_count,
                downloaded_count=stats.downloaded_count,
                wanted_count=stats.wanted_count,
                size_on_disk=stats.size_on_disk,
            ),
        )


class _MagazineBody(ApiModel):
    alternate_titles: list[ShortText] | None = Field(default=None, max_length=50)
    publisher: str | None = Field(default=None, max_length=255)
    language: str | None = Field(default=None, max_length=16)
    category: str | None = Field(default=None, max_length=100)
    frequency: Frequency | None = None
    first_issue_year: int | None = Field(default=None, ge=1600, le=2200)
    tags: list[Tag] | None = Field(default=None, max_length=50)
    quality_profile_id: int | None = None
    root_folder_id: int | None = None
    folder: str | None = Field(default=None, max_length=255)
    monitored: bool | None = None
    poster_url: str | None = Field(default=None, max_length=2048)
    search_cutoff: date | None = None
    grab_new_specials: bool | None = None
    issue_naming_template: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=10_000)

    def fields(self) -> MagazineFields:
        provided = set(self.model_fields_set)
        return MagazineFields(**self.model_dump(), provided=provided)


class MagazineCreate(_MagazineBody):
    title: str = Field(min_length=1, max_length=255)


class MagazineUpdate(_MagazineBody):
    title: str | None = Field(default=None, min_length=1, max_length=255)


class GenerateIssuesBody(ApiModel):
    # Needed for date numbering; optional with issue numbering (adds expected publish dates).
    start: date | None = None
    count: int = Field(ge=1, le=520)
    monitored: bool = False
    # Set to number issues 360, 361, ... instead of by date.
    first_number: int | None = Field(default=None, ge=0, le=10_000_000)


class GenerateIssuesResult(ApiModel):
    created: list[IssueResource]
    skipped: int


class CsvImportBody(ApiModel):
    csv: str = Field(max_length=5_000_000)
    create_missing: bool = False
    monitored: bool = False


class CsvRowError(ApiModel):
    row: int
    message: str


class CsvImportResultResource(ApiModel):
    issues_created: int
    issues_updated: int
    issues_unchanged: int
    magazines_created: list[str]
    errors: list[CsvRowError]


def _resource(session: SessionDep, magazine: Magazine) -> MagazineResource:
    stats = magazines.magazine_stats(session, [magazine.id]).get(magazine.id)
    return MagazineResource.of(magazine, stats)


@router.get("", response_model=list[MagazineResource])
def list_magazines(
    session: SessionDep, paging: PagingDep, response: Response
) -> list[MagazineResource]:
    stmt = paging.apply(session, select(Magazine).order_by(Magazine.sort_title), response)
    rows = list(session.scalars(stmt))
    stats = magazines.magazine_stats(session, [m.id for m in rows])
    return [MagazineResource.of(m, stats.get(m.id)) for m in rows]


@router.post("", response_model=MagazineResource, status_code=status.HTTP_201_CREATED)
def create_magazine(body: MagazineCreate, session: SessionDep) -> MagazineResource:
    magazine = magazines.create_magazine(session, body.fields())
    session.commit()
    return _resource(session, magazine)


@router.post("/import", response_model=CsvImportResultResource)
def import_issues_csv(body: CsvImportBody, session: SessionDep) -> CsvImportResultResource:
    """Bulk-add issues from CSV with columns magazine, issue, date (YYYY-MM-DD), issue_title."""
    result = import_csv(session, body.csv, body.create_missing, body.monitored)
    session.commit()
    return CsvImportResultResource(
        issues_created=result.issues_created,
        issues_updated=result.issues_updated,
        issues_unchanged=result.issues_unchanged,
        magazines_created=result.magazines_created,
        errors=[CsvRowError(row=e.row, message=e.message) for e in result.errors],
    )


class MagazineEditorBody(ApiModel):
    """Changes applied to every listed magazine; fields left out are unchanged."""

    ids: list[int] = Field(min_length=1, max_length=1000)
    monitored: bool | None = None
    quality_profile_id: int | None = None
    root_folder_id: int | None = None
    grab_new_specials: bool | None = None

    def fields(self) -> MagazineFields:
        provided = set(self.model_fields_set) - {"ids"}
        return MagazineFields(**self.model_dump(exclude={"ids"}), provided=provided)


class MagazineIdsBody(ApiModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


@router.put("/editor", response_model=list[MagazineResource])
def edit_magazines(body: MagazineEditorBody, session: SessionDep) -> list[MagazineResource]:
    """Bulk edit (the library's table view). All or nothing: one invalid change saves none."""
    fields = body.fields()
    updated = [magazines.update_magazine(session, i, fields) for i in dict.fromkeys(body.ids)]
    session.commit()
    stats = magazines.magazine_stats(session, [m.id for m in updated])
    return [MagazineResource.of(m, stats.get(m.id)) for m in updated]


@router.post("/editor/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_magazines(body: MagazineIdsBody, session: SessionDep) -> None:
    """Bulk delete: magazine and issue records only; files on disk are not touched."""
    for magazine_id in dict.fromkeys(body.ids):
        magazines.delete_magazine(session, magazine_id)
    session.commit()


@router.get("/{magazine_id}", response_model=MagazineResource)
def get_magazine(magazine_id: int, session: SessionDep) -> MagazineResource:
    return _resource(session, magazines.get_magazine(session, magazine_id))


@router.get(
    "/{magazine_id}/cover",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}}}, 304: {}, 404: {}},
)
def get_cover(magazine_id: int, session: SessionDep, request: Request) -> Response:
    """JPEG of the earliest downloaded issue's cover (first page)."""
    magazine = magazines.get_magazine(session, magazine_id)
    path = magazine_cover(magazine, request.app.state.settings.cover_cache_dir)
    if path is None:
        raise NotFoundError(f"No readable cover for {magazine.title}")
    etag = f'"{path.stem}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type="image/jpeg", headers=headers)


@router.patch("/{magazine_id}", response_model=MagazineResource)
def update_magazine(
    magazine_id: int, body: MagazineUpdate, session: SessionDep
) -> MagazineResource:
    magazine = magazines.update_magazine(session, magazine_id, body.fields())
    session.commit()
    return _resource(session, magazine)


@router.delete("/{magazine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_magazine(magazine_id: int, session: SessionDep) -> None:
    """Deletes the magazine and its issue records. Files on disk are not touched."""
    magazines.delete_magazine(session, magazine_id)
    session.commit()


@router.post("/{magazine_id}/generate-issues", response_model=GenerateIssuesResult)
def generate_issues(
    magazine_id: int, body: GenerateIssuesBody, session: SessionDep
) -> GenerateIssuesResult:
    """Create expected issues: by date from the frequency, or numbered from ``firstNumber``."""
    result = magazines.generate_issues(
        session, magazine_id, body.start, body.count, body.monitored, body.first_number
    )
    session.commit()
    return GenerateIssuesResult(
        created=[IssueResource.of(i) for i in result.created], skipped=result.skipped
    )
