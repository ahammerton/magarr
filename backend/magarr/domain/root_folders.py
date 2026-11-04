from __future__ import annotations

import os
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.models import Magazine, RootFolder


def normalize_path(raw: str) -> str:
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        raise DomainError("Root folder path must be absolute")
    # Keep the user's spelling (no symlink resolution) but drop trailing slashes and "..".
    return os.path.normpath(path)


def free_space(path: str) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def is_accessible(path: str) -> bool:
    return Path(path).is_dir() and os.access(path, os.R_OK | os.X_OK)


def get_root_folder(session: Session, root_id: int) -> RootFolder:
    root = session.get(RootFolder, root_id)
    if root is None:
        raise NotFoundError(f"Root folder {root_id} not found")
    return root


def add_root_folder(session: Session, raw_path: str) -> RootFolder:
    path = normalize_path(raw_path)
    if not Path(path).is_dir():
        raise DomainError(f"Folder does not exist: {path}")
    if session.scalar(select(RootFolder.id).where(RootFolder.path == path)) is not None:
        raise ConflictError(f"Root folder already added: {path}")
    is_first = session.scalar(select(func.count()).select_from(RootFolder)) == 0
    root = RootFolder(path=path, is_default=is_first)
    session.add(root)
    session.flush()
    return root


def set_default(session: Session, root_id: int) -> RootFolder:
    root = get_root_folder(session, root_id)
    for other in session.scalars(select(RootFolder)):
        other.is_default = other.id == root.id
    session.flush()
    return root


def delete_root_folder(session: Session, root_id: int) -> None:
    root = get_root_folder(session, root_id)
    in_use = session.scalar(
        select(func.count()).select_from(Magazine).where(Magazine.root_folder_id == root_id)
    )
    if in_use:
        raise ConflictError(f"Root folder is used by {in_use} magazine(s)")
    was_default = root.is_default
    session.delete(root)
    session.flush()
    if was_default:
        replacement = session.scalar(select(RootFolder).order_by(RootFolder.id).limit(1))
        if replacement:
            replacement.is_default = True
            session.flush()


def default_root_folder_id(session: Session) -> int | None:
    return session.scalar(
        select(RootFolder.id).order_by(RootFolder.is_default.desc(), RootFolder.id).limit(1)
    )
