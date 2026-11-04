"""Notification connection CRUD: settings validated per service, secrets masked."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.core.forms import masked, validated
from magarr.core.netguard import check_configured_url
from magarr.domain.enums import NotificationImplementation
from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.models import Notification
from magarr.notifications.events import NotificationEvent
from magarr.notifications.providers import IMPLEMENTATIONS

MAX_TEMPLATE = 2000
URL_FIELDS = {"webhook_url", "url", "server_url"}


@dataclass
class NotificationFields:
    name: str | None = None
    implementation: NotificationImplementation | None = None
    enabled: bool | None = None
    events: list[NotificationEvent] | None = None
    settings: dict[str, Any] | None = None
    templates: dict[str, str] | None = None
    provided: set[str] = field(default_factory=set)


def get_notification(session: Session, notification_id: int) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None:
        raise NotFoundError(f"Notification {notification_id} not found")
    return row


def masked_settings(row: Notification) -> dict[str, Any]:
    model = IMPLEMENTATIONS[NotificationImplementation(row.implementation)].settings_model
    return masked(model, row.settings)


def validate_settings(
    implementation: NotificationImplementation,
    raw: dict[str, Any],
    existing: Notification | None = None,
) -> dict[str, Any]:
    same = existing is not None and existing.implementation == implementation.value
    model = IMPLEMENTATIONS[implementation].settings_model
    result = validated(model, raw, existing.settings if same else None)
    for key in URL_FIELDS & result.keys():
        check_configured_url(result[key])
    return result


def _templates(raw: dict[str, str] | None) -> dict[str, str]:
    """Overrides only; a blank template means "use the default"."""
    result = {}
    for key, value in (raw or {}).items():
        try:
            NotificationEvent(key)
        except ValueError as exc:
            raise DomainError(f"Unknown event in templates: {key}") from exc
        if len(value) > MAX_TEMPLATE:
            raise DomainError(f"The {key} template is longer than {MAX_TEMPLATE} characters")
        if value.strip():
            result[key] = value
    return result


def _check_name(session: Session, name: str, exclude_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise DomainError("Name cannot be empty")
    stmt = select(Notification.id).where(func.lower(Notification.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Notification.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"A notification named '{name}' already exists")
    return name


def create_notification(session: Session, fields: NotificationFields) -> Notification:
    if fields.implementation is None:
        raise DomainError("implementation is required")
    row = Notification(
        name=_check_name(session, fields.name or ""),
        implementation=fields.implementation.value,
        enabled=True if fields.enabled is None else fields.enabled,
        events=[e.value for e in (fields.events or list(NotificationEvent))],
        settings=validate_settings(fields.implementation, fields.settings or {}),
        templates=_templates(fields.templates),
    )
    session.add(row)
    session.flush()
    return row


def update_notification(
    session: Session, notification_id: int, fields: NotificationFields
) -> Notification:
    row = get_notification(session, notification_id)
    implementation = fields.implementation or NotificationImplementation(row.implementation)
    if "name" in fields.provided:
        row.name = _check_name(session, fields.name or "", exclude_id=row.id)
    if "enabled" in fields.provided and fields.enabled is not None:
        row.enabled = fields.enabled
    if "events" in fields.provided and fields.events is not None:
        row.events = [e.value for e in fields.events]
    if "templates" in fields.provided:
        row.templates = _templates(fields.templates)
    if "settings" in fields.provided or "implementation" in fields.provided:
        row.settings = validate_settings(implementation, fields.settings or row.settings, row)
        row.implementation = implementation.value
    session.flush()
    return row


def delete_notification(session: Session, notification_id: int) -> None:
    session.delete(get_notification(session, notification_id))
    session.flush()
