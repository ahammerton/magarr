"""Import settings and remote path mappings."""

from __future__ import annotations

import posixpath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from magarr.domain.enums import ImportMode
from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.models import MediaSettings, RemotePathMapping

_OCTAL = set("01234567")


def get_media_settings(session: Session) -> MediaSettings:
    row = session.scalar(select(MediaSettings).order_by(MediaSettings.id).limit(1))
    if row is None:
        row = MediaSettings(
            auto_import=True,
            usenet_import_mode=ImportMode.MOVE.value,
            torrent_import_mode=ImportMode.HARDLINK.value,
            remove_completed_downloads=True,
            recycle_bin="",
            file_chmod="",
            folder_chmod="",
        )
        session.add(row)
        session.flush()
    return row


def update_media_settings(session: Session, values: dict[str, Any]) -> MediaSettings:
    row = get_media_settings(session)
    for key in ("usenet_import_mode", "torrent_import_mode"):
        if key in values:
            try:
                values[key] = ImportMode(values[key]).value
            except ValueError as exc:
                raise DomainError(f"Unknown import mode: {values[key]}") from exc
    for key in ("file_chmod", "folder_chmod"):
        if key in values:
            text = (values[key] or "").strip()
            if text and (not set(text) <= _OCTAL or not 3 <= len(text) <= 4):
                raise DomainError(f"{key} must be an octal mode such as 664 or 0775")
            values[key] = text
    if "recycle_bin" in values:
        path = (values["recycle_bin"] or "").strip()
        if path and not posixpath.isabs(path):
            raise DomainError("Recycle bin must be an absolute path (or empty to delete files)")
        values["recycle_bin"] = path.rstrip("/") or ""
    for key in ("chown_user", "chown_group"):
        if key in values and values[key] is not None and values[key] < 0:
            raise DomainError(f"{key} must be a non-negative id")
    for key, value in values.items():
        setattr(row, key, value)
    session.flush()
    return row


def _norm(path: str) -> str:
    """POSIX-normalize, keep a trailing slash off (except root)."""
    text = posixpath.normpath(path.strip().replace("\\", "/"))
    return text if text != "." else ""


def add_mapping(
    session: Session, host: str, remote_path: str, local_path: str
) -> RemotePathMapping:
    host, remote, local = host.strip(), _norm(remote_path), _norm(local_path)
    if not host:
        raise DomainError("Host is required (the download client's host)")
    if not remote.startswith("/") or not local.startswith("/"):
        raise DomainError("Remote and local paths must be absolute")
    exists = session.scalar(
        select(RemotePathMapping.id).where(
            RemotePathMapping.host == host, RemotePathMapping.remote_path == remote
        )
    )
    if exists is not None:
        raise ConflictError(f"A mapping for {host}:{remote} already exists")
    mapping = RemotePathMapping(host=host, remote_path=remote, local_path=local)
    session.add(mapping)
    session.flush()
    return mapping


def delete_mapping(session: Session, mapping_id: int) -> None:
    mapping = session.get(RemotePathMapping, mapping_id)
    if mapping is None:
        raise NotFoundError(f"Remote path mapping {mapping_id} not found")
    session.delete(mapping)
    session.flush()


def map_path(session: Session, host: str, path: str) -> str:
    """Translate a client-reported path using the longest matching mapping for that host."""
    norm = _norm(path)
    best: RemotePathMapping | None = None
    for mapping in session.scalars(select(RemotePathMapping)):
        if mapping.host.casefold() != host.strip().casefold():
            continue
        remote = mapping.remote_path
        if (norm == remote or norm.startswith(remote.rstrip("/") + "/")) and (
            best is None or len(remote) > len(best.remote_path)
        ):
            best = mapping
    if best is None:
        return norm
    rest = norm[len(best.remote_path.rstrip("/")) :].lstrip("/")
    return posixpath.join(best.local_path, rest) if rest else best.local_path
