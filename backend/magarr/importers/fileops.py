"""Filesystem side of importing: transfer, collisions, permissions, recycle bin."""

from __future__ import annotations

import errno
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from magarr.domain.enums import ImportMode
from magarr.domain.errors import DomainError

logger = logging.getLogger(__name__)


class ImportFileError(DomainError):
    status_code = 409


def unique_destination(dest: Path, current: Path | None = None) -> Path:
    """dest, or "name - copy.ext", "name - copy 2.ext"... if something else is already there."""
    if not dest.exists() or (current is not None and dest == current):
        return dest
    for n in range(1, 1000):
        suffix = " - copy" if n == 1 else f" - copy {n}"
        candidate = dest.with_name(f"{dest.stem}{suffix}{dest.suffix}")
        if not candidate.exists():
            return candidate
    raise ImportFileError(f"Too many files named like {dest.name}")


def _copy_atomically(src: Path, dest: Path) -> None:
    """Copy next to the destination then rename, so readers never see a half-written file."""
    partial = dest.with_name(f".{dest.name}.partial")
    try:
        shutil.copy2(src, partial)
        os.replace(partial, dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def transfer(src: Path, dest: Path, mode: ImportMode) -> ImportMode:
    """Move, copy or hard-link ``src`` to ``dest``. Returns the mode actually used."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode is ImportMode.HARDLINK:
        try:
            os.link(src, dest)
            return ImportMode.HARDLINK
        except OSError as exc:
            logger.info(
                "Hard link failed, copying instead", extra={"file": str(src), "error": str(exc)}
            )
            _copy_atomically(src, dest)
            return ImportMode.COPY
    if mode is ImportMode.COPY:
        _copy_atomically(src, dest)
        return ImportMode.COPY
    try:
        os.replace(src, dest)  # atomic on the same filesystem
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EACCES, errno.EPERM):
            raise
        # Across filesystems, or the download client's files are read-only to Magarr (e.g.
        # SABnzbd on a NAS writing as its own user): copy, then remove the source if allowed.
        _copy_atomically(src, dest)  # still raises if the file can't even be read
        try:
            src.unlink()
        except OSError as unlink_error:
            logger.warning(
                "Imported a copy: not allowed to remove the original",
                extra={"file": str(src), "error": str(unlink_error)},
            )
            return ImportMode.COPY
    return ImportMode.MOVE


def apply_permissions(
    path: Path,
    library_root: Path,
    file_mode: str,
    folder_mode: str,
    uid: int | None,
    gid: int | None,
) -> None:
    """chmod/chown the file and the folders created under the library root. Failures are
    logged, not fatal: a NAS share may not support them."""

    def apply(target: Path, mode: str) -> None:
        try:
            if mode:
                target.chmod(int(mode, 8))
            if uid is not None or gid is not None:
                os.chown(target, uid if uid is not None else -1, gid if gid is not None else -1)
        except OSError as exc:
            logger.warning(
                "Could not set permissions", extra={"path": str(target), "error": str(exc)}
            )

    apply(path, file_mode)
    folder = path.parent
    while folder != library_root and library_root in folder.parents:
        apply(folder, folder_mode)
        folder = folder.parent


def dispose(path: Path, recycle_bin: str, library_root: Path) -> str:
    """Delete a replaced file, or move it to the recycle bin. Returns what happened."""
    if not path.exists():
        return "missing"
    if recycle_bin:
        relative = (
            path.relative_to(library_root) if library_root in path.parents else Path(path.name)
        )
        target = Path(recycle_bin) / relative
        if target.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            target = target.with_name(f"{target.stem} ({stamp}){target.suffix}")
        transfer(path, target, ImportMode.MOVE)
        return f"moved to {target}"
    path.unlink()
    return "deleted"


def prune_empty_dirs(start: Path, stop: Path) -> None:
    """Remove ``start`` and its parents while they are empty, never ``stop`` or above it."""
    folder, stop = start.resolve(), stop.resolve()
    while folder != stop and stop in folder.parents:
        try:
            folder.rmdir()  # only succeeds when empty
        except OSError:
            return
        folder = folder.parent


def ensure_inside(path: Path, root: Path) -> None:
    resolved, base = path.resolve(), root.resolve()
    if resolved != base and base not in resolved.parents:
        raise ImportFileError(f"Refusing to write outside the library: {path}")
