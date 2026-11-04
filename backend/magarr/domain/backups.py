"""Backups: a zip of the database and config.yaml in <config>/backups.

Restoring stages the backup in <config>/restore; it is applied at the next start, before the
database is opened (the current state is backed up first), so nothing is swapped under a
running app. The API then restarts Magarr (Docker's restart policy brings it back).
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.script import ScriptDirectory

from magarr.core.config import CONFIG_FILE_NAME
from magarr.core.db import alembic_config
from magarr.domain.errors import DomainError, NotFoundError

logger = logging.getLogger(__name__)

DB_NAME = "magarr.db"
KEEP_SCHEDULED = 7
MAX_RESTORE_BYTES = 2 * 1024**3
_NAME = re.compile(r"^magarr_backup_(?P<kind>manual|scheduled|pre_restore)_[\d._]+\.zip$")


@dataclass(frozen=True)
class BackupInfo:
    name: str
    kind: str
    size: int
    created: datetime


def backup_dir(config_dir: Path) -> Path:
    return config_dir / "backups"


def _restore_dir(config_dir: Path) -> Path:
    return config_dir / "restore"


def _copy_database(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)  # consistent even while the app is writing (WAL)


def create_backup(config_dir: Path, database: Path, kind: str = "manual") -> BackupInfo:
    folder = backup_dir(config_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y.%m.%d_%H.%M.%S.%f")[:-3]  # unique to the millisecond
    target = folder / f"magarr_backup_{kind}_{stamp}.zip"
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        copy = Path(tmp) / DB_NAME
        _copy_database(database, copy)
        partial = target.with_suffix(".partial")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy, DB_NAME)
            config = config_dir / CONFIG_FILE_NAME
            if config.exists():
                archive.write(config, CONFIG_FILE_NAME)
        partial.replace(target)
    if kind == "scheduled":
        for old in [b for b in list_backups(config_dir) if b.kind == "scheduled"][KEEP_SCHEDULED:]:
            (folder / old.name).unlink(missing_ok=True)
    logger.info("Backup created", extra={"backup": target.name})
    return _info(target)


def _info(path: Path) -> BackupInfo:
    stat = path.stat()
    match = _NAME.match(path.name)
    return BackupInfo(
        name=path.name,
        kind=match["kind"] if match else "manual",
        size=stat.st_size,
        created=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def list_backups(config_dir: Path) -> list[BackupInfo]:
    folder = backup_dir(config_dir)
    if not folder.is_dir():
        return []
    found = [_info(p) for p in folder.iterdir() if _NAME.match(p.name)]
    return sorted(found, key=lambda b: b.name.rsplit("_", 2)[-2:], reverse=True)  # by timestamp


def backup_path(config_dir: Path, name: str) -> Path:
    if not _NAME.match(name):  # also rules out "../" tricks
        raise NotFoundError(f"No backup named {name}")
    path = backup_dir(config_dir) / name
    if not path.is_file():
        raise NotFoundError(f"No backup named {name}")
    return path


def delete_backup(config_dir: Path, name: str) -> None:
    backup_path(config_dir, name).unlink()


def _check_database(path: Path) -> None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DomainError("The backup's database is damaged")
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError as exc:
        raise DomainError("The backup doesn't contain a Magarr database") from exc
    known = {s.revision for s in ScriptDirectory.from_config(alembic_config()).walk_revisions()}
    if row is None or row[0] not in known:
        raise DomainError("The backup is from a newer version of Magarr; upgrade Magarr first")


def stage_restore(config_dir: Path, archive_path: Path) -> None:
    """Check a backup zip and stage it for the next start."""
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise DomainError("That isn't a Magarr backup (not a zip file)") from exc
    with archive:
        names = set(archive.namelist())
        if DB_NAME not in names or not names <= {DB_NAME, CONFIG_FILE_NAME}:
            raise DomainError(f"A Magarr backup holds {DB_NAME} and {CONFIG_FILE_NAME} only")
        if sum(i.file_size for i in archive.infolist()) > MAX_RESTORE_BYTES:
            raise DomainError("The backup is too large")
        staging = _restore_dir(config_dir)
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for name in names:
            with archive.open(name) as src, (staging / name).open("wb") as dst:
                shutil.copyfileobj(src, dst)
    try:
        _check_database(staging / DB_NAME)
    except DomainError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    logger.info("Restore staged; it will be applied when Magarr restarts")


def apply_staged_restore(config_dir: Path, database: Path) -> bool:
    """At startup, before the database is opened: swap in a staged restore."""
    staging = _restore_dir(config_dir)
    staged_db = staging / DB_NAME
    if not staged_db.is_file():
        return False
    if database.exists():
        create_backup(config_dir, database, kind="pre_restore")
    for suffix in ("-wal", "-shm"):
        database.with_name(database.name + suffix).unlink(missing_ok=True)
    shutil.move(staged_db, database)
    if (staging / CONFIG_FILE_NAME).is_file():
        shutil.move(staging / CONFIG_FILE_NAME, config_dir / CONFIG_FILE_NAME)
    shutil.rmtree(staging, ignore_errors=True)
    logger.info("Restored the database (and config) from a backup")
    return True
