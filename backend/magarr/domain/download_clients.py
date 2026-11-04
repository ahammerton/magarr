"""Download client CRUD. Settings are validated by the implementation's schema; secrets are
masked on read and kept when the mask is sent back."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.core.forms import masked, validated
from magarr.core.netguard import check_configured_url
from magarr.domain.enums import DownloadClientImplementation, Protocol
from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.models import DownloadClient, DownloadSettings
from magarr.downloaders.registry import settings_model


@dataclass
class ClientFields:
    name: str | None = None
    implementation: DownloadClientImplementation | None = None
    enabled: bool | None = None
    priority: int | None = None
    settings: dict[str, Any] | None = None
    provided: set[str] = field(default_factory=set)


def get_client(session: Session, client_id: int) -> DownloadClient:
    client = session.get(DownloadClient, client_id)
    if client is None:
        raise NotFoundError(f"Download client {client_id} not found")
    return client


def masked_settings(client: DownloadClient) -> dict[str, Any]:
    return masked(
        settings_model(DownloadClientImplementation(client.implementation)), client.settings
    )


def validate_settings(
    implementation: DownloadClientImplementation,
    raw: dict[str, Any],
    existing: DownloadClient | None = None,
) -> dict[str, Any]:
    """Validate against the implementation's schema; masked secrets keep the stored value."""
    same = existing is not None and existing.implementation == implementation.value
    model = settings_model(implementation)
    result = validated(model, raw, existing.settings if same else None)
    check_configured_url(model.model_validate(result).base_url())
    return result


def _check_name(session: Session, name: str, exclude_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise DomainError("Name cannot be empty")
    stmt = select(DownloadClient.id).where(func.lower(DownloadClient.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(DownloadClient.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"A download client named '{name}' already exists")
    return name


def _check_priority(priority: int) -> int:
    if not 1 <= priority <= 50:
        raise DomainError("Priority must be between 1 and 50")
    return priority


def create_client(session: Session, fields: ClientFields) -> DownloadClient:
    if fields.implementation is None:
        raise DomainError("implementation is required")
    client = DownloadClient(
        name=_check_name(session, fields.name or ""),
        implementation=fields.implementation.value,
        enabled=True if fields.enabled is None else fields.enabled,
        priority=_check_priority(1 if fields.priority is None else fields.priority),
        settings=validate_settings(fields.implementation, fields.settings or {}),
    )
    session.add(client)
    session.flush()
    return client


def update_client(session: Session, client_id: int, fields: ClientFields) -> DownloadClient:
    client = get_client(session, client_id)
    implementation = fields.implementation or DownloadClientImplementation(client.implementation)
    if "name" in fields.provided:
        client.name = _check_name(session, fields.name or "", exclude_id=client.id)
    if "enabled" in fields.provided and fields.enabled is not None:
        client.enabled = fields.enabled
    if "priority" in fields.provided and fields.priority is not None:
        client.priority = _check_priority(fields.priority)
    if "settings" in fields.provided or "implementation" in fields.provided:
        client.settings = validate_settings(
            implementation, fields.settings or client.settings, client
        )
        client.implementation = implementation.value
    session.flush()
    return client


def delete_client(session: Session, client_id: int) -> None:
    session.delete(get_client(session, client_id))
    session.flush()


def client_for(session: Session, protocol: Protocol) -> DownloadClient | None:
    """The enabled client with the best priority for a protocol."""
    implementations = [i.value for i in DownloadClientImplementation if i.protocol is protocol]
    return session.scalar(
        select(DownloadClient)
        .where(DownloadClient.enabled.is_(True), DownloadClient.implementation.in_(implementations))
        .order_by(DownloadClient.priority, DownloadClient.id)
        .limit(1)
    )


def get_download_settings(session: Session) -> DownloadSettings:
    row = session.scalar(select(DownloadSettings).order_by(DownloadSettings.id).limit(1))
    if row is None:
        row = DownloadSettings(redownload_failed=True, max_retries=3)
        session.add(row)
        session.flush()
    return row
