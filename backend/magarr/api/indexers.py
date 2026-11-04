from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import Field
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.schemas import ApiModel, Tag
from magarr.domain.enums import IndexerImplementation, IndexerSource, Protocol
from magarr.domain.errors import DomainError
from magarr.domain.models import Indexer
from magarr.indexers import health, prowlarr, service
from magarr.indexers.caps import Caps
from magarr.indexers.categories import CATEGORY_NAMES, DEFAULT_CATEGORIES
from magarr.indexers.client import IndexerRequestError
from magarr.indexers.runtime import IndexerRuntime
from magarr.indexers.service import MASKED_KEY, IndexerFields

router = APIRouter(prefix="/api/v1", tags=["Indexers"])


def get_runtime(request: Request) -> IndexerRuntime:
    return request.app.state.indexer_runtime


RuntimeDep = Annotated[IndexerRuntime, Depends(get_runtime)]


class CategoryResource(ApiModel):
    id: int
    name: str


class IndexerResource(ApiModel):
    id: int
    name: str
    implementation: IndexerImplementation
    protocol: Protocol
    base_url: str
    api_path: str
    api_key: str  # masked
    categories: list[int]
    priority: int
    enabled: bool
    tags: list[str]
    request_interval: float
    source: IndexerSource
    prowlarr_id: int | None
    supported_categories: list[CategoryResource]
    consecutive_failures: int
    disabled_until: datetime | None
    last_error: str | None
    last_success: datetime | None

    @classmethod
    def of(cls, indexer: Indexer) -> "IndexerResource":
        caps = Caps.from_json(indexer.caps)
        supported = [
            CategoryResource(id=c.id, name=c.name)
            for top in caps.categories
            for c in [top, *top.subcategories]
            if 7000 <= c.id < 8000
        ]
        implementation = IndexerImplementation(indexer.implementation)
        return cls(
            id=indexer.id,
            name=indexer.name,
            implementation=implementation,
            protocol=implementation.protocol,
            base_url=indexer.base_url,
            api_path=indexer.api_path,
            api_key=MASKED_KEY if indexer.api_key else "",
            categories=indexer.categories or list(DEFAULT_CATEGORIES),
            priority=indexer.priority,
            enabled=indexer.enabled,
            tags=indexer.tags or [],
            request_interval=indexer.request_interval,
            source=IndexerSource(indexer.source),
            prowlarr_id=indexer.prowlarr_id,
            supported_categories=supported,
            consecutive_failures=indexer.consecutive_failures,
            disabled_until=health.disabled_until(indexer),
            last_error=indexer.last_error,
            last_success=indexer.last_success,
        )


class _IndexerBody(ApiModel):
    implementation: IndexerImplementation | None = None
    api_path: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=255)
    categories: list[int] | None = Field(default=None, max_length=200)
    priority: int | None = None
    enabled: bool | None = None
    tags: list[Tag] | None = Field(default=None, max_length=50)
    request_interval: float | None = None

    def fields(self) -> IndexerFields:
        return IndexerFields(**self.model_dump(), provided=set(self.model_fields_set))


class IndexerCreate(_IndexerBody):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=1024)


class IndexerUpdate(_IndexerBody):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=1024)


class IndexerTestBody(IndexerCreate):
    # When testing edits to a saved indexer, its stored key is used if the key is still masked.
    id: int | None = None
    name: str = Field(default="Test", max_length=100)

    def fields(self) -> IndexerFields:
        data = self.model_dump(exclude={"id"})
        return IndexerFields(**data, provided=set(self.model_fields_set) - {"id"})


class TestResult(ApiModel):
    ok: bool
    message: str
    supported_categories: list[CategoryResource] = Field(default_factory=list)


class ProwlarrConfigResource(ApiModel):
    url: str
    api_key: str
    last_sync: datetime | None


class ProwlarrConfigBody(ApiModel):
    url: str = Field(max_length=1024)
    api_key: str = Field(max_length=255)


class SkippedIndexer(ApiModel):
    name: str
    reason: str


class SyncResultResource(ApiModel):
    added: list[str]
    updated: list[str]
    removed: list[str]
    skipped: list[SkippedIndexer]


def _book_categories(caps: Caps) -> list[CategoryResource]:
    return [
        CategoryResource(id=c.id, name=c.name)
        for top in caps.categories
        for c in [top, *top.subcategories]
        if 7000 <= c.id < 8000
    ]


@router.get("/indexer/categories", response_model=list[CategoryResource])
def list_categories() -> list[CategoryResource]:
    return [CategoryResource(id=k, name=v) for k, v in CATEGORY_NAMES.items()]


@router.get("/indexer", response_model=list[IndexerResource])
def list_indexers(session: SessionDep) -> list[IndexerResource]:
    rows = session.scalars(select(Indexer).order_by(Indexer.priority, Indexer.name))
    return [IndexerResource.of(i) for i in rows]


@router.post("/indexer", response_model=IndexerResource, status_code=status.HTTP_201_CREATED)
def create_indexer(body: IndexerCreate, session: SessionDep) -> IndexerResource:
    indexer = service.create_indexer(session, body.fields())
    session.commit()
    return IndexerResource.of(indexer)


@router.post("/indexer/test", response_model=TestResult)
async def test_unsaved(
    body: IndexerTestBody, session: SessionDep, runtime: RuntimeDep
) -> TestResult:
    """Test settings before saving (or edits to an existing indexer)."""
    existing = service.get_indexer(session, body.id) if body.id is not None else None
    try:
        endpoint = service.unsaved_endpoint(body.fields(), existing)
        caps = await service.test_endpoint(endpoint, runtime)
    except (IndexerRequestError, DomainError) as exc:
        return TestResult(ok=False, message=str(exc))
    return TestResult(ok=True, message="Connection OK", supported_categories=_book_categories(caps))


@router.post("/indexer/sync-prowlarr", response_model=SyncResultResource)
async def sync_prowlarr(session: SessionDep, runtime: RuntimeDep) -> SyncResultResource:
    config = prowlarr.get_config(session)
    if not config.url or not config.api_key:
        raise DomainError("Set the Prowlarr URL and API key first")
    try:
        remote = await prowlarr.fetch_indexers(runtime, config.url, config.api_key)
    except IndexerRequestError as exc:
        raise DomainError(str(exc)) from exc
    result = prowlarr.apply_sync(session, config, remote)
    session.commit()
    return SyncResultResource(
        added=result.added,
        updated=result.updated,
        removed=result.removed,
        skipped=[SkippedIndexer(name=n, reason=r) for n, r in result.skipped],
    )


@router.get("/indexer/{indexer_id}", response_model=IndexerResource)
def get_indexer(indexer_id: int, session: SessionDep) -> IndexerResource:
    return IndexerResource.of(service.get_indexer(session, indexer_id))


@router.patch("/indexer/{indexer_id}", response_model=IndexerResource)
def update_indexer(indexer_id: int, body: IndexerUpdate, session: SessionDep) -> IndexerResource:
    indexer = service.update_indexer(session, indexer_id, body.fields())
    session.commit()
    return IndexerResource.of(indexer)


@router.delete("/indexer/{indexer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_indexer(indexer_id: int, session: SessionDep) -> None:
    service.delete_indexer(session, indexer_id)
    session.commit()


@router.post("/indexer/{indexer_id}/test", response_model=TestResult)
async def test_saved(indexer_id: int, session: SessionDep, runtime: RuntimeDep) -> TestResult:
    """Test a saved indexer. Success clears any failure backoff and refreshes its caps."""
    indexer = service.get_indexer(session, indexer_id)
    try:
        caps = await service.test_endpoint(service.endpoint_for(indexer), runtime)
    except IndexerRequestError as exc:
        health.record_failure(indexer, str(exc))
        session.commit()
        return TestResult(ok=False, message=str(exc))
    indexer.caps = caps.to_json()
    health.record_success(indexer)
    session.commit()
    return TestResult(ok=True, message="Connection OK", supported_categories=_book_categories(caps))


@router.get("/config/prowlarr", response_model=ProwlarrConfigResource, tags=["Prowlarr"])
def get_prowlarr(session: SessionDep) -> ProwlarrConfigResource:
    config = prowlarr.get_config(session)
    session.commit()
    return ProwlarrConfigResource(
        url=config.url, api_key=MASKED_KEY if config.api_key else "", last_sync=config.last_sync
    )


@router.put("/config/prowlarr", response_model=ProwlarrConfigResource, tags=["Prowlarr"])
def save_prowlarr(body: ProwlarrConfigBody, session: SessionDep) -> ProwlarrConfigResource:
    config = prowlarr.get_config(session)
    config.url = service.normalize_url(body.url) if body.url.strip() else ""
    if body.api_key != MASKED_KEY:
        config.api_key = body.api_key.strip()
    session.commit()
    return ProwlarrConfigResource(
        url=config.url, api_key=MASKED_KEY if config.api_key else "", last_sync=config.last_sync
    )


@router.post("/config/prowlarr/test", response_model=TestResult, tags=["Prowlarr"])
async def test_prowlarr(
    body: ProwlarrConfigBody, session: SessionDep, runtime: RuntimeDep
) -> TestResult:
    api_key = prowlarr.get_config(session).api_key if body.api_key == MASKED_KEY else body.api_key
    try:
        version = await prowlarr.test_connection(runtime, body.url, api_key.strip())
    except (IndexerRequestError, DomainError) as exc:
        return TestResult(ok=False, message=str(exc))
    return TestResult(ok=True, message=f"Connected to Prowlarr {version}")
