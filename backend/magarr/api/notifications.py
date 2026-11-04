"""Notification connections: Discord, Slack, webhook, ntfy, Pushover."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import Field
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.downloadclients import FieldSchema, TestResult
from magarr.api.schemas import ApiModel, SettingsMap
from magarr.core.forms import schema_fields
from magarr.domain.enums import NotificationImplementation
from magarr.domain.models import Notification
from magarr.notifications import service
from magarr.notifications.base import Message
from magarr.notifications.dispatch import Dispatcher
from magarr.notifications.events import (
    DEFAULT_TEMPLATES,
    TEST_TEMPLATE,
    TOKENS,
    NotificationEvent,
    render,
)
from magarr.notifications.providers import IMPLEMENTATIONS
from magarr.notifications.service import NotificationFields

router = APIRouter(prefix="/api/v1", tags=["Notifications"])

SAMPLE = {
    "magazine": "National Geographic",
    "issue": "2026-10",
    "release": "National.Geographic.October.2026.HYBRiD.MAGAZiNE",
    "quality": "pdf",
    "client": "SABnzbd",
    "source": "RSS sync",
    "path": "/magazines/National Geographic/National Geographic - 2026-10 - Issue 2026-10.pdf",
    "message": "Example message",
}


class NotificationImplementationSchema(ApiModel):
    implementation: NotificationImplementation
    name: str
    fields: list[FieldSchema]


class TokenResource(ApiModel):
    name: str
    description: str


class NotificationSchema(ApiModel):
    implementations: list[NotificationImplementationSchema]
    events: list[NotificationEvent]
    default_templates: dict[str, str]
    tokens: list[TokenResource]


class NotificationResource(ApiModel):
    id: int
    name: str
    implementation: NotificationImplementation
    enabled: bool
    events: list[NotificationEvent]
    settings: dict[str, Any]  # secrets masked
    templates: dict[str, str]
    last_sent: datetime | None
    last_error: str | None

    @classmethod
    def of(cls, row: Notification) -> "NotificationResource":
        return cls(
            id=row.id,
            name=row.name,
            implementation=NotificationImplementation(row.implementation),
            enabled=row.enabled,
            events=[NotificationEvent(e) for e in row.events or []],
            settings=service.masked_settings(row),
            templates=row.templates or {},
            last_sent=row.last_sent,
            last_error=row.last_error,
        )


class NotificationBody(ApiModel):
    name: str | None = Field(default=None, max_length=100)
    implementation: NotificationImplementation | None = None
    enabled: bool | None = None
    events: list[NotificationEvent] | None = Field(default=None, max_length=10)
    settings: SettingsMap | None = None
    templates: dict[str, str] | None = Field(default=None, max_length=10)

    def fields(self) -> NotificationFields:
        return NotificationFields(**self.model_dump(), provided=set(self.model_fields_set))


class NotificationTestBody(ApiModel):
    implementation: NotificationImplementation
    settings: SettingsMap
    # When editing a saved connection, masked secrets resolve to its stored values.
    id: int | None = None


class PreviewBody(ApiModel):
    template: str = Field(max_length=service.MAX_TEMPLATE)


class PreviewResult(ApiModel):
    title: str
    body: str


@router.get("/notification/schema", response_model=NotificationSchema)
def notification_schema() -> NotificationSchema:
    return NotificationSchema(
        implementations=[
            NotificationImplementationSchema(
                implementation=implementation,
                name=cls.display_name,
                fields=[FieldSchema(**f) for f in schema_fields(cls.settings_model)],
            )
            for implementation, cls in IMPLEMENTATIONS.items()
        ],
        events=list(NotificationEvent),
        default_templates={k.value: v for k, v in DEFAULT_TEMPLATES.items()},
        tokens=[TokenResource(name=k, description=v) for k, v in TOKENS.items()],
    )


@router.post("/notification/preview", response_model=PreviewResult)
def preview(body: PreviewBody) -> PreviewResult:
    """Render a template with example values."""
    title, text = render(body.template, {**SAMPLE, "event": "import"})
    return PreviewResult(title=title, body=text)


@router.get("/notification", response_model=list[NotificationResource])
def list_notifications(session: SessionDep) -> list[NotificationResource]:
    rows = session.scalars(select(Notification).order_by(Notification.name))
    return [NotificationResource.of(r) for r in rows]


@router.post(
    "/notification", response_model=NotificationResource, status_code=status.HTTP_201_CREATED
)
def create_notification(body: NotificationBody, session: SessionDep) -> NotificationResource:
    row = service.create_notification(session, body.fields())
    session.commit()
    return NotificationResource.of(row)


@router.get("/notification/{notification_id}", response_model=NotificationResource)
def get_notification(notification_id: int, session: SessionDep) -> NotificationResource:
    return NotificationResource.of(service.get_notification(session, notification_id))


@router.patch("/notification/{notification_id}", response_model=NotificationResource)
def update_notification(
    notification_id: int, body: NotificationBody, session: SessionDep
) -> NotificationResource:
    row = service.update_notification(session, notification_id, body.fields())
    session.commit()
    return NotificationResource.of(row)


@router.delete("/notification/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: int, session: SessionDep) -> None:
    service.delete_notification(session, notification_id)
    session.commit()


def _dispatcher(request: Request) -> Dispatcher:
    return request.app.state.notifications


async def _send_test(request: Request, row: Notification) -> TestResult:
    title, body = render(TEST_TEMPLATE, {})
    error = await _dispatcher(request).send_one(row, Message("test", title, body, SAMPLE))
    if error:
        return TestResult(ok=False, message=error)
    return TestResult(ok=True, message=f"Test message sent to {row.name or 'the service'}")


@router.post("/notification/test", response_model=TestResult)
async def test_settings(body: NotificationTestBody, session: SessionDep, request: Request):
    """Send a test message with unsaved settings."""
    existing = service.get_notification(session, body.id) if body.id is not None else None
    settings = service.validate_settings(body.implementation, body.settings, existing)
    probe = Notification(name="", implementation=body.implementation.value, settings=settings)
    return await _send_test(request, probe)


@router.post("/notification/{notification_id}/test", response_model=TestResult)
async def test_saved(notification_id: int, session: SessionDep, request: Request) -> TestResult:
    row = service.get_notification(session, notification_id)
    result = await _send_test(request, row)
    session.commit()  # keeps last_sent / last_error
    return result
