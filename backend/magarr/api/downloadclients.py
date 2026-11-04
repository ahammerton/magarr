from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import Field
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.schemas import ApiModel, SettingsMap
from magarr.core.forms import schema_fields
from magarr.domain import download_clients as service
from magarr.domain.download_clients import ClientFields
from magarr.domain.enums import DownloadClientImplementation, Protocol
from magarr.domain.errors import DomainError
from magarr.domain.models import DownloadClient
from magarr.downloaders.base import DownloadClientError
from magarr.downloaders.registry import IMPLEMENTATIONS, build_client

router = APIRouter(prefix="/api/v1", tags=["Download clients"])


class FieldSchema(ApiModel):
    name: str
    label: str
    type: str  # string | number | boolean | password | select
    required: bool
    default: Any = None
    description: str | None = None
    options: list[str] | None = None


class ImplementationSchema(ApiModel):
    implementation: DownloadClientImplementation
    name: str
    protocol: Protocol
    fields: list[FieldSchema]


class DownloadClientResource(ApiModel):
    id: int
    name: str
    implementation: DownloadClientImplementation
    protocol: Protocol
    enabled: bool
    priority: int
    settings: dict[str, Any]  # secrets masked

    @classmethod
    def of(cls, client: DownloadClient) -> "DownloadClientResource":
        implementation = DownloadClientImplementation(client.implementation)
        return cls(
            id=client.id,
            name=client.name,
            implementation=implementation,
            protocol=implementation.protocol,
            enabled=client.enabled,
            priority=client.priority,
            settings=service.masked_settings(client),
        )


class DownloadClientBody(ApiModel):
    name: str | None = Field(default=None, max_length=100)
    implementation: DownloadClientImplementation | None = None
    enabled: bool | None = None
    priority: int | None = None
    settings: SettingsMap | None = None

    def fields(self) -> ClientFields:
        return ClientFields(**self.model_dump(), provided=set(self.model_fields_set))


class TestBody(ApiModel):
    implementation: DownloadClientImplementation
    settings: SettingsMap
    # When editing a saved client, masked secrets resolve to its stored values.
    id: int | None = None


class TestResult(ApiModel):
    ok: bool
    message: str
    warnings: list[str] = Field(default_factory=list)


class DownloadSettingsResource(ApiModel):
    redownload_failed: bool
    # Automatic retries per issue before giving up.
    max_retries: int = Field(default=3, ge=0, le=20)


@router.get("/downloadclient/schema", response_model=list[ImplementationSchema])
def schema() -> list[ImplementationSchema]:
    result = []
    for implementation, cls in IMPLEMENTATIONS.items():
        fields = [FieldSchema(**f) for f in schema_fields(cls.settings_model)]
        result.append(
            ImplementationSchema(
                implementation=implementation,
                name=cls.display_name,
                protocol=cls.protocol,
                fields=fields,
            )
        )
    return result


@router.get("/downloadclient", response_model=list[DownloadClientResource])
def list_clients(session: SessionDep) -> list[DownloadClientResource]:
    rows = session.scalars(
        select(DownloadClient).order_by(DownloadClient.priority, DownloadClient.name)
    )
    return [DownloadClientResource.of(c) for c in rows]


@router.post(
    "/downloadclient", response_model=DownloadClientResource, status_code=status.HTTP_201_CREATED
)
def create_client(body: DownloadClientBody, session: SessionDep) -> DownloadClientResource:
    client = service.create_client(session, body.fields())
    session.commit()
    return DownloadClientResource.of(client)


@router.post("/downloadclient/test", response_model=TestResult)
async def test_unsaved(body: TestBody, request: Request, session: SessionDep) -> TestResult:
    existing = service.get_client(session, body.id) if body.id is not None else None
    try:
        settings = service.validate_settings(body.implementation, body.settings, existing)
        client = build_client(body.implementation, settings, request.app.state.indexer_runtime.http)
        outcome = await client.test()
    except (DownloadClientError, DomainError) as exc:
        return TestResult(ok=False, message=str(exc))
    return TestResult(
        ok=True,
        message=f"Connected to {client.display_name} {outcome.version}",
        warnings=outcome.warnings,
    )


@router.get("/downloadclient/{client_id}", response_model=DownloadClientResource)
def get_client(client_id: int, session: SessionDep) -> DownloadClientResource:
    return DownloadClientResource.of(service.get_client(session, client_id))


@router.patch("/downloadclient/{client_id}", response_model=DownloadClientResource)
def update_client(
    client_id: int, body: DownloadClientBody, session: SessionDep
) -> DownloadClientResource:
    client = service.update_client(session, client_id, body.fields())
    session.commit()
    return DownloadClientResource.of(client)


@router.delete("/downloadclient/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: int, session: SessionDep) -> None:
    service.delete_client(session, client_id)
    session.commit()


@router.post("/downloadclient/{client_id}/test", response_model=TestResult)
async def test_saved(client_id: int, request: Request, session: SessionDep) -> TestResult:
    row = service.get_client(session, client_id)
    client = build_client(
        DownloadClientImplementation(row.implementation),
        row.settings,
        request.app.state.indexer_runtime.http,
    )
    try:
        outcome = await client.test()
    except DownloadClientError as exc:
        return TestResult(ok=False, message=str(exc))
    return TestResult(
        ok=True,
        message=f"Connected to {client.display_name} {outcome.version}",
        warnings=outcome.warnings,
    )


@router.get("/config/downloads", response_model=DownloadSettingsResource, tags=["Download clients"])
def get_download_settings(session: SessionDep) -> DownloadSettingsResource:
    row = service.get_download_settings(session)
    session.commit()
    return DownloadSettingsResource(
        redownload_failed=row.redownload_failed, max_retries=row.max_retries
    )


@router.put("/config/downloads", response_model=DownloadSettingsResource, tags=["Download clients"])
def save_download_settings(
    body: DownloadSettingsResource, session: SessionDep
) -> DownloadSettingsResource:
    row = service.get_download_settings(session)
    row.redownload_failed = body.redownload_failed
    row.max_retries = body.max_retries
    session.commit()
    return DownloadSettingsResource(
        redownload_failed=row.redownload_failed, max_retries=row.max_retries
    )
