"""Wanted list, calendar and automation settings (brief §5 Phase 5)."""

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import contains_eager

from magarr.api.deps import SessionDep
from magarr.api.issues import IssueResource, current_downloads
from magarr.api.schemas import ApiModel
from magarr.domain.automation_settings import (
    get_automation_settings,
    update_automation_settings,
)
from magarr.domain.enums import IssueStatus
from magarr.domain.errors import DomainError
from magarr.domain.models import Issue, Magazine

router = APIRouter(prefix="/api/v1", tags=["Automation"])

MAX_CALENDAR_DAYS = 400


class MagazineIssueResource(IssueResource):
    magazine_title: str
    magazine_monitored: bool


def _with_magazines(session, issues: list[Issue]) -> list[MagazineIssueResource]:
    downloads = current_downloads(session, [i.id for i in issues])
    return [
        MagazineIssueResource(
            **IssueResource.of(i, downloads.get(i.id)).model_dump(),
            magazine_title=i.magazine.title,
            magazine_monitored=i.magazine.monitored,
        )
        for i in issues
    ]


class WantedPage(ApiModel):
    total: int
    page: int
    page_size: int
    records: list[MagazineIssueResource]


@router.get("/wanted", response_model=WantedPage)
def wanted(
    session: SessionDep,
    magazine_id: Annotated[int | None, Query(alias="magazineId")] = None,
    status_filter: Annotated[Literal["wanted", "missing"], Query(alias="status")] = "wanted",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=500)] = 50,
) -> WantedPage:
    """Issues without a file: wanted (monitored) or missing (not monitored). Newest first."""
    stmt = (
        select(Issue)
        .join(Magazine, Issue.magazine_id == Magazine.id)
        .options(contains_eager(Issue.magazine))
        .where(Issue.status == IssueStatus(status_filter).value)
    )
    if magazine_id is not None:
        stmt = stmt.where(Issue.magazine_id == magazine_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        session.scalars(
            stmt.order_by(
                # DESC already puts undated issues last, so the (status, publish_date) index
                # serves the order.
                Issue.publish_date.desc(),
                Magazine.sort_title,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return WantedPage(
        total=total, page=page, page_size=page_size, records=_with_magazines(session, rows)
    )


class WantedSearchBody(ApiModel):
    issue_ids: list[int] = Field(min_length=1, max_length=500)


class WantedSearchResult(ApiModel):
    queued: int


@router.post(
    "/wanted/search", response_model=WantedSearchResult, status_code=status.HTTP_202_ACCEPTED
)
async def wanted_search(body: WantedSearchBody, request: Request) -> WantedSearchResult:
    """Search the issues in the background and grab the best release for each."""
    return WantedSearchResult(queued=request.app.state.automation.search_issues(body.issue_ids))


@router.get("/calendar", response_model=list[MagazineIssueResource])
def calendar(
    session: SessionDep,
    start: date,
    end: date,
    unmonitored: bool = False,
) -> list[MagazineIssueResource]:
    """Issues published between ``start`` and ``end`` (inclusive)."""
    if end < start:
        raise DomainError("end must not be before start")
    if end - start > timedelta(days=MAX_CALENDAR_DAYS):
        raise DomainError(f"The calendar shows at most {MAX_CALENDAR_DAYS} days at a time")
    stmt = (
        select(Issue)
        .join(Magazine, Issue.magazine_id == Magazine.id)
        .options(contains_eager(Issue.magazine))
        .where(Issue.publish_date >= start, Issue.publish_date <= end)
    )
    if not unmonitored:
        stmt = stmt.where(Magazine.monitored.is_(True))
    rows = list(session.scalars(stmt.order_by(Issue.publish_date, Magazine.sort_title)))
    return _with_magazines(session, rows)


class JobStatusResource(ApiModel):
    name: Literal["expected", "rss", "backlog"]
    last_run: datetime | None
    last_result: str | None


class AutomationSettingsResource(ApiModel):
    monitoring_enabled: bool
    rss_interval_minutes: int
    backlog_interval_minutes: int
    backlog_batch_size: int
    expected_lookahead_days: int


class AutomationResource(AutomationSettingsResource):
    jobs: list[JobStatusResource]


def _resource(row, request: Request) -> AutomationResource:
    automation = getattr(request.app.state, "automation", None)
    statuses = automation.status if automation else {}
    return AutomationResource(
        monitoring_enabled=row.monitoring_enabled,
        rss_interval_minutes=row.rss_interval_minutes,
        backlog_interval_minutes=row.backlog_interval_minutes,
        backlog_batch_size=row.backlog_batch_size,
        expected_lookahead_days=row.expected_lookahead_days,
        jobs=[
            JobStatusResource(
                name=name,
                last_run=statuses[name].last_run if name in statuses else None,
                last_result=statuses[name].last_result if name in statuses else None,
            )
            for name in ("expected", "rss", "backlog")
        ],
    )


@router.get("/config/automation", response_model=AutomationResource)
def get_automation(session: SessionDep, request: Request) -> AutomationResource:
    row = get_automation_settings(session)
    session.commit()
    return _resource(row, request)


@router.put("/config/automation", response_model=AutomationResource)
def save_automation(
    body: AutomationSettingsResource, session: SessionDep, request: Request
) -> AutomationResource:
    row = update_automation_settings(session, body.model_dump())
    session.commit()
    return _resource(row, request)
