"""Import completed downloads (and manually chosen files) into the library (brief §5 Phase 4).

For a download: find the magazine files in its folder (skipping junk and samples), decide which
issue each one is, keep the best file per issue, check it is an upgrade, then move/copy/hard-link
it to the path the naming scheme gives, record it, and clean up.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import shutil
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from magarr.domain.enums import (
    EXTENSION_FORMATS,
    DownloadStatus,
    FileFormat,
    HistoryEventType,
    ImportMode,
    Protocol,
)
from magarr.domain.history import record
from magarr.domain.issues import resolve_status
from magarr.domain.media_settings import get_media_settings, map_path
from magarr.domain.models import Download, Issue, IssueFile, Magazine, MediaSettings
from magarr.domain.naming import issue_relative_path
from magarr.domain.naming_config import get_scheme, naming_input
from magarr.domain.qualities import QUALITIES, quality_for_format
from magarr.importers.fileops import (
    ImportFileError,
    apply_permissions,
    dispose,
    ensure_inside,
    prune_empty_dirs,
    transfer,
    unique_destination,
)
from magarr.importers.matching import match_issue, specialise
from magarr.importers.parsing import parse_filename, parse_release

logger = logging.getLogger(__name__)

# On network shares a file the download client still has open (finishing post-processing)
# can't be moved for a moment, and SMB reports that as "permission denied". Such errors are
# retried on each poll for this long after the download completed before the import is blocked.
RETRY_FILE_ERRORS_FOR = timedelta(minutes=10)
_MAYBE_TRANSIENT = {errno.EACCES, errno.EPERM, errno.EBUSY, errno.ETXTBSY, errno.EAGAIN}

_SAMPLE = re.compile(r"(?:^|[\W_])sample(?:[\W_]|$)", re.IGNORECASE)
_QUALITY_NAMES = {q.id: q.name for q in QUALITIES}
# Files a release ships besides the magazine; a folder holding only these can be deleted.
JUNK_SUFFIXES = {
    ".nfo",
    ".diz",
    ".sfv",
    ".nzb",
    ".txt",
    ".url",
    ".jpg",
    ".jpeg",
    ".png",
    ".srr",
    ".par2",
    ".db",
}


@dataclass
class Candidate:
    path: Path
    size: int
    format: FileFormat | None
    issue: Issue | None
    quality: str
    rejections: list[str] = field(default_factory=list)
    # Known even when the issue isn't (manual import suggests it from the folder name).
    magazine: Magazine | None = None


@dataclass
class FileOutcome:
    path: str
    issue_id: int | None
    imported_to: str | None = None
    upgraded: bool = False
    skipped: str | None = None
    # A move that had to fall back to a copy because the original couldn't be removed.
    copied_instead: bool = False


def _still_retrying(download: Download, now: datetime) -> bool:
    completed = download.completed_at
    if completed is None:
        return True
    if completed.tzinfo is None:  # SQLite hands back naive datetimes
        completed = completed.replace(tzinfo=UTC)
    return now - completed < RETRY_FILE_ERRORS_FOR


@dataclass
class ImportResult:
    outcomes: list[FileOutcome] = field(default_factory=list)

    @property
    def imported(self) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.imported_to]


def media_files(root: Path) -> list[Path]:
    """Magazine files under ``root`` (or ``root`` itself), skipping hidden files and samples."""
    if root.is_file():
        return [root] if root.suffix.lower() in EXTENSION_FORMATS else []
    found = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            path = Path(current, name)
            if name.startswith(".") or path.suffix.lower() not in EXTENSION_FORMATS:
                continue
            if _SAMPLE.search(path.stem):
                continue
            found.append(path)
    return found


def file_quality(path: Path, release_title: str | None) -> str:
    fmt = EXTENSION_FORMATS.get(path.suffix.lower())
    base = quality_for_format(fmt)
    # The file name rarely says "HQ"; the release name does. Trust it for the matching format.
    if release_title:
        release = parse_release(release_title)
        if release.quality == "pdf_hires" and fmt is FileFormat.PDF:
            return "pdf_hires"
    return base


def _position(magazine: Magazine, quality: str) -> int:
    for item in magazine.quality_profile.items:
        if item.quality == quality:
            return item.position
    return 10_000


def check_upgrade(
    magazine: Magazine, issue: Issue, quality: str, size: int, automatic: bool
) -> str | None:
    """Reason to skip, or None to import."""
    profile = magazine.quality_profile
    item = next((i for i in profile.items if i.quality == quality), None)
    name = _QUALITY_NAMES.get(quality, quality)
    if automatic and (item is None or not item.allowed):
        return f"Quality {name} is not allowed by profile '{profile.name}'"
    existing = issue.file
    if existing is None:
        return None
    if not (magazine.path / existing.relative_path).exists():
        return None  # the recorded file is gone: replace the record
    have, want = _position(magazine, existing.quality), _position(magazine, quality)
    if want < have:
        return None
    if want == have and size > existing.size and not automatic:
        return None  # manual import of the same quality: the user chose it
    have_name = _QUALITY_NAMES.get(existing.quality, existing.quality)
    return f"Not an upgrade: the issue already has a {have_name} file"


def candidates_for_download(download: Download, files: list[Path]) -> list[Candidate]:
    """Assign each file to an issue of the grabbed issue's magazine."""
    grabbed = download.issue
    magazine = grabbed.magazine
    matched: list[Candidate] = []
    unmatched: list[Path] = []
    for path in files:
        parsed = specialise(parse_filename(path.name), magazine)
        issue = match_issue(parsed, magazine.issues) if parsed.issue_key else None
        quality = file_quality(path, download.title)
        size = path.stat().st_size
        if issue is not None:
            matched.append(
                Candidate(path, size, EXTENSION_FORMATS.get(path.suffix.lower()), issue, quality)
            )
        else:
            unmatched.append(path)

    covered = {c.issue.id for c in matched}
    if grabbed.id not in covered and len(unmatched) == 1:
        # Obfuscated or oddly named: the release itself said which issue this is.
        path = unmatched.pop()
        matched.append(
            Candidate(
                path,
                path.stat().st_size,
                EXTENSION_FORMATS.get(path.suffix.lower()),
                grabbed,
                file_quality(path, download.title),
            )
        )
    for path in unmatched:
        matched.append(
            Candidate(
                path,
                path.stat().st_size,
                EXTENSION_FORMATS.get(path.suffix.lower()),
                None,
                file_quality(path, None),
                ["Could not tell which issue this file is"],
            )
        )

    # Several files for one issue (PDF + EPUB, say): keep the best by profile, then size.
    best: dict[int, Candidate] = {}
    for candidate in matched:
        if candidate.issue is None:
            continue
        key = candidate.issue.id
        rank = (_position(magazine, candidate.quality), -candidate.size)
        if key not in best or rank < (_position(magazine, best[key].quality), -best[key].size):
            if key in best:
                best[key].rejections.append("A better file for the same issue is in this download")
            best[key] = candidate
        else:
            candidate.rejections.append("A better file for the same issue is in this download")
    return matched


def import_file(
    session: Session,
    settings: MediaSettings,
    candidate: Candidate,
    mode: ImportMode,
    source_title: str,
    download: Download | None,
) -> FileOutcome:
    """Place one file in the library for its issue. Caller decided it should be imported."""
    issue = candidate.issue
    if issue is None:
        raise ImportFileError(f"No issue chosen for {candidate.path.name}")
    magazine = issue.magazine
    library_root = Path(magazine.root_folder.path)
    folder = magazine.path
    fmt = candidate.format.value if candidate.format else candidate.path.suffix.lstrip(".").lower()

    naming = replace(
        naming_input(magazine, issue, with_file=False),
        format=fmt,
        quality=_QUALITY_NAMES.get(candidate.quality),
    )
    relative = issue_relative_path(naming, get_scheme(session), magazine.issue_naming_template)
    existing = issue.file
    current = folder / existing.relative_path if existing else None
    if current is not None and not current.exists():
        current = None
    dest = unique_destination(folder / relative, current)
    ensure_inside(dest, folder)  # never another magazine's folder, the root or anywhere else

    # Never lose the old file to a failed transfer: set it aside, restore it on failure, and
    # only dispose of it (recycle bin or delete) once the new file is in place.
    aside: Path | None = None
    if current is not None and current == dest:
        aside = current.with_name(f".{current.name}.replaced")
        os.replace(current, aside)
    try:
        used = transfer(candidate.path, dest, mode)
    except BaseException:
        if aside is not None and current is not None:
            os.replace(aside, current)
        raise
    replaced = None
    if aside is not None and current is not None:
        replaced = dispose(aside, settings.recycle_bin, library_root, name=current.name)
    elif current is not None:
        replaced = dispose(current, settings.recycle_bin, library_root)
        # e.g. the naming changed from "2026/..." to flat: don't leave an empty "2026" behind.
        prune_empty_dirs(current.parent, folder)
    apply_permissions(
        dest,
        library_root,
        settings.file_chmod,
        settings.folder_chmod,
        settings.chown_user,
        settings.chown_group,
    )

    upgraded = existing is not None
    relative_posix = dest.relative_to(folder).as_posix()
    if existing is None:
        issue.file = IssueFile(
            relative_path=relative_posix,
            size=candidate.size,
            format=fmt,
            quality=candidate.quality,
            date_added=datetime.now(UTC),
        )
    else:
        old = existing.relative_path
        existing.relative_path, existing.size = relative_posix, candidate.size
        existing.format, existing.quality = fmt, candidate.quality
        existing.date_added = datetime.now(UTC)
        record(
            session,
            HistoryEventType.FILE_DELETED,
            old,
            issue,
            reason="upgrade",
            result=replaced or "missing",
        )
    # Got it: stop monitoring, so it isn't searched for again (nor re-wanted if the file goes).
    issue.monitored = False
    resolve_status(issue)
    record(
        session,
        HistoryEventType.UPGRADED if upgraded else HistoryEventType.IMPORTED,
        source_title,
        issue,
        download_id=download.id if download else None,
        source_path=str(candidate.path),
        imported_path=str(dest),
        mode=used.value,
        quality=candidate.quality,
    )
    session.flush()
    logger.info(
        "Imported file", extra={"file": str(candidate.path), "to": str(dest), "mode": used.value}
    )
    return FileOutcome(
        path=str(candidate.path),
        issue_id=issue.id,
        imported_to=str(dest),
        upgraded=upgraded,
        copied_instead=mode is ImportMode.MOVE and used is ImportMode.COPY,
    )


def _is_only_junk(folder: Path) -> bool:
    return all(
        Path(name).suffix.lower() in JUNK_SUFFIXES
        for _, _, files in os.walk(folder)
        for name in files
    )


def local_output_path(session: Session, download: Download) -> Path | None:
    if not download.output_path:
        return None
    client = download.download_client
    host = client.settings.get("host", "") if client else ""
    return Path(map_path(session, host, download.output_path))


def import_download(session: Session, download: Download, *, cleanup: bool = True) -> ImportResult:
    """Automatic import of a pending download. Sets the download's status and message."""
    settings = get_media_settings(session)
    result = ImportResult()
    if download.issue is None:
        download.status, download.message = (
            DownloadStatus.IMPORT_BLOCKED.value,
            "The issue was deleted",
        )
        return result
    local = local_output_path(session, download)
    if local is None or not local.exists():
        reported = download.output_path or "(no path reported)"
        hint = " Add a remote path mapping if the client sees this folder under a different path."
        download.status = DownloadStatus.PENDING_IMPORT.value
        download.message = (
            f"Magarr can't see {local or reported}"
            + (f" (client reported {reported})." if local and str(local) != reported else ".")
            + hint
        )
        return result

    files = media_files(local)
    if not files:
        download.status = DownloadStatus.IMPORT_BLOCKED.value
        download.message = f"No magazine files found in {local}"
        record(
            session,
            HistoryEventType.IMPORT_FAILED,
            download.title,
            download.issue,
            download_id=download.id,
            message=download.message,
        )
        return result

    mode = ImportMode(
        settings.torrent_import_mode
        if download.protocol == Protocol.TORRENT.value
        else settings.usenet_import_mode
    )
    transient: list[str] = []
    for candidate in candidates_for_download(download, files):
        if candidate.rejections:
            result.outcomes.append(
                FileOutcome(str(candidate.path), None, skipped=candidate.rejections[0])
            )
            continue
        magazine = candidate.issue.magazine
        reason = check_upgrade(
            magazine, candidate.issue, candidate.quality, candidate.size, automatic=True
        )
        if reason:
            result.outcomes.append(
                FileOutcome(str(candidate.path), candidate.issue.id, skipped=reason)
            )
            continue
        try:
            result.outcomes.append(
                import_file(session, settings, candidate, mode, download.title, download)
            )
        except OSError as exc:
            logger.warning(
                "Import file error", extra={"file": str(candidate.path), "error": str(exc)}
            )
            if exc.errno in _MAYBE_TRANSIENT:
                transient.append(str(exc))
            result.outcomes.append(
                FileOutcome(str(candidate.path), candidate.issue.id, skipped=f"File error: {exc}")
            )

    skipped = [o for o in result.outcomes if o.skipped]
    if transient and not result.imported:
        if _still_retrying(download, datetime.now(UTC)):
            # Probably still in use by the download client; the next poll tries again.
            download.status = DownloadStatus.PENDING_IMPORT.value
            download.message = f"Waiting for the file to become available ({transient[0]})"
            session.flush()
            return result
        skipped[0].skipped = (
            f"{skipped[0].skipped}. Still failing after "
            f"{int(RETRY_FILE_ERRORS_FOR.total_seconds() // 60)} minutes: check that Magarr's "
            "user can read and delete files in the download folder and write to the library"
        )
    if result.imported:
        download.status = DownloadStatus.IMPORTED.value
        download.message = (
            f"{len(skipped)} file(s) not imported: {skipped[0].skipped}" if skipped else None
        )
        if any(o.copied_instead for o in result.outcomes):
            download.message = (
                "Imported as a copy: Magarr isn't allowed to move or delete the download "
                "client's files, so the originals are still in the download folder. Let others "
                "modify completed downloads (SABnzbd: Config → Folders → Permissions for "
                "completed downloads, e.g. 777)."
            )
        if (
            cleanup
            and mode is ImportMode.MOVE
            and not skipped
            and settings.remove_completed_downloads
        ):
            _cleanup(download, local)
    else:
        download.status = DownloadStatus.IMPORT_BLOCKED.value
        download.message = skipped[0].skipped if skipped else "Nothing to import"
        logger.warning(
            "Import blocked", extra={"release": download.title, "reason": download.message}
        )
        record(
            session,
            HistoryEventType.IMPORT_FAILED,
            download.title,
            download.issue,
            download_id=download.id,
            message=download.message,
        )
    session.flush()
    return result


def _cleanup(download: Download, local: Path) -> None:
    """Delete the leftover download folder when only junk (.nfo, .diz, ...) is left in it."""
    library = Path(download.issue.magazine.root_folder.path).resolve()
    folder = local.resolve()
    if (
        not folder.is_dir()
        or len(folder.parts) < 3
        or folder == library
        or folder in library.parents
    ):
        return  # never delete a top-level folder or one that contains the library
    if not _is_only_junk(folder):
        return
    try:
        shutil.rmtree(folder)
        logger.info("Removed leftover download folder", extra={"folder": str(folder)})
    except OSError as exc:
        logger.warning(
            "Could not remove download folder", extra={"folder": str(folder), "error": str(exc)}
        )
