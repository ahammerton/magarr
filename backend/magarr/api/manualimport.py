"""Manual import: review files in a download or any folder, choose issues, import."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from magarr.api.deps import SessionDep
from magarr.api.schemas import ApiModel, PathText
from magarr.domain.enums import EXTENSION_FORMATS, DownloadStatus, ImportMode, Protocol
from magarr.domain.errors import DomainError, NotFoundError
from magarr.domain.issue_service import get_issue
from magarr.domain.media_settings import get_media_settings
from magarr.domain.models import Download, Issue, IssueFile, Magazine
from magarr.domain.qualities import QUALITY_IDS
from magarr.importers.importer import (
    Candidate,
    candidates_for_download,
    check_upgrade,
    file_quality,
    import_file,
    local_output_path,
    media_files,
)
from magarr.importers.matching import match_issue, match_magazine, specialise
from magarr.importers.parsing import parse_filename

router = APIRouter(prefix="/api/v1/manualimport", tags=["Manual import"])


class ManualImportItem(ApiModel):
    path: str
    relative_path: str
    size: int
    format: str | None
    quality: str
    magazine_id: int | None
    issue_id: int | None
    issue_number: str | None  # what the file name says
    warnings: list[str]


class ManualImportScan(ApiModel):
    folder: str
    download_id: int | None
    items: list[ManualImportItem]


class ImportChoice(ApiModel):
    path: PathText
    issue_id: int
    quality: str | None = Field(default=None, max_length=32)


class ManualImportBody(ApiModel):
    files: list[ImportChoice] = Field(min_length=1, max_length=500)
    download_id: int | None = None
    mode: ImportMode | None = None  # default: the protocol's mode for downloads, else move


class ManualImportOutcome(ApiModel):
    path: str
    issue_id: int | None
    imported_to: str | None
    upgraded: bool
    error: str | None


def _load_magazines(session: SessionDep) -> list[Magazine]:
    return list(
        session.scalars(
            select(Magazine).options(selectinload(Magazine.issues).selectinload(Issue.file))
        )
    )


def _issue_key(candidate: Candidate) -> str | None:
    """The issue the file name suggests, named the way this magazine's specials are."""
    parsed = parse_filename(candidate.path.name)
    magazine = candidate.issue.magazine if candidate.issue else candidate.magazine
    return (specialise(parsed, magazine) if magazine else parsed).issue_key


def _warnings(candidate: Candidate) -> list[str]:
    warnings = list(candidate.rejections)
    if candidate.issue is not None:
        reason = check_upgrade(
            candidate.issue.magazine,
            candidate.issue,
            candidate.quality,
            candidate.size,
            automatic=True,
        )
        if reason:
            warnings.append(reason)
    return warnings


def _scan_folder(session: SessionDep, folder: Path) -> list[Candidate]:
    magazines = _load_magazines(session)
    result = []
    for path in media_files(folder):
        parsed = parse_filename(path.name)
        magazine = match_magazine(parsed.title, magazines) if parsed.title else None
        if magazine is None:
            magazine = match_magazine(path.parent.name, magazines)
        if magazine is not None:
            parsed = specialise(parsed, magazine)
        issue = match_issue(parsed, magazine.issues) if magazine and parsed.issue_key else None
        rejections = (
            [] if issue else ["Choose the issue" if magazine else "Choose the magazine and issue"]
        )
        result.append(
            Candidate(
                path,
                path.stat().st_size,
                EXTENSION_FORMATS.get(path.suffix.lower()),
                issue,
                file_quality(path, None),
                rejections,
                magazine=magazine,
            )
        )
    return result


@router.get("", response_model=ManualImportScan)
def scan(
    session: SessionDep,
    download_id: Annotated[int | None, Query(alias="downloadId")] = None,
    path: str | None = None,
) -> ManualImportScan:
    if download_id is not None:
        download = session.get(Download, download_id)
        if download is None:
            raise NotFoundError(f"Download {download_id} not found")
        folder = local_output_path(session, download)
        if folder is None or not folder.exists():
            raise DomainError(
                f"Magarr can't see the download's folder ({download.output_path}); "
                "add a remote path mapping"
            )
        candidates = (
            candidates_for_download(download, media_files(folder))
            if download.issue
            else _scan_folder(session, folder)
        )
    elif path:
        folder = Path(path).expanduser()
        if not folder.is_absolute() or not folder.exists():
            raise DomainError("Enter an absolute path to an existing folder or file")
        candidates = _scan_folder(session, folder)
    else:
        raise DomainError("Give a downloadId or a path")
    base = folder if folder.is_dir() else folder.parent
    return ManualImportScan(
        folder=str(folder),
        download_id=download_id,
        items=[
            ManualImportItem(
                path=str(c.path),
                relative_path=c.path.relative_to(base).as_posix(),
                size=c.size,
                format=c.format.value if c.format else None,
                quality=c.quality,
                magazine_id=c.issue.magazine_id
                if c.issue
                else (c.magazine.id if c.magazine else None),
                issue_id=c.issue.id if c.issue else None,
                issue_number=_issue_key(c),
                warnings=_warnings(c),
            )
            for c in candidates
        ],
    )


def _library_files(session: SessionDep) -> dict[Path, str]:
    """Every file the library already records, with the issue it belongs to."""
    rows = session.execute(
        select(Magazine, Issue.issue_number, IssueFile.relative_path)
        .join(Issue, Issue.magazine_id == Magazine.id)
        .join(IssueFile, IssueFile.issue_id == Issue.id)
    )
    return {
        magazine.path / relative: f"{magazine.title} {number}"
        for magazine, number, relative in rows
    }


def _check_source(path: Path, download_folder: Path | None, library: dict[Path, str]) -> None:
    """Only plain magazine files, named by absolute path, and inside the download if given."""
    if not path.is_absolute() or ".." in path.parts:
        raise DomainError(f"Give the file's full path: {path}")
    if path.is_symlink():
        raise DomainError(f"Not importing a symbolic link: {path}")
    if not path.is_file() or path.suffix.lower() not in EXTENSION_FORMATS:
        raise DomainError(f"Not a magazine file: {path}")
    if download_folder is not None:
        folder = download_folder.resolve()
        if path.resolve() != folder and folder not in path.resolve().parents:
            raise DomainError(f"{path} is not part of this download")
    if owner := library.get(path):
        # Moving it would leave that issue pointing at nothing.
        raise DomainError(f"{path.name} is already the file of {owner}")


@router.post("", response_model=list[ManualImportOutcome])
def run_import(
    body: ManualImportBody, request: Request, session: SessionDep
) -> list[ManualImportOutcome]:
    settings = get_media_settings(session)
    download = session.get(Download, body.download_id) if body.download_id is not None else None
    if body.download_id is not None and download is None:
        raise NotFoundError(f"Download {body.download_id} not found")
    mode = body.mode
    if mode is None:
        if download is not None and download.protocol == Protocol.TORRENT.value:
            mode = ImportMode(settings.torrent_import_mode)
        else:
            mode = ImportMode(settings.usenet_import_mode)

    download_folder = local_output_path(session, download) if download is not None else None
    library = _library_files(session)
    outcomes: list[ManualImportOutcome] = []
    for choice in body.files:
        path = Path(choice.path)
        try:
            _check_source(path, download_folder, library)
            issue = get_issue(session, choice.issue_id)
            quality = choice.quality or file_quality(path, download.title if download else None)
            if quality not in QUALITY_IDS:
                raise DomainError(f"Unknown quality {quality}")
            candidate = Candidate(
                path, path.stat().st_size, EXTENSION_FORMATS[path.suffix.lower()], issue, quality
            )
            outcome = import_file(
                session,
                settings,
                candidate,
                mode,
                download.title if download else path.name,
                download,
            )
            session.commit()
            outcomes.append(
                ManualImportOutcome(
                    path=str(path),
                    issue_id=issue.id,
                    imported_to=outcome.imported_to,
                    upgraded=outcome.upgraded,
                    error=None,
                )
            )
        except (DomainError, OSError) as exc:
            session.rollback()
            message = exc.message if isinstance(exc, DomainError) else str(exc)
            outcomes.append(
                ManualImportOutcome(
                    path=str(path),
                    issue_id=choice.issue_id,
                    imported_to=None,
                    upgraded=False,
                    error=message,
                )
            )
    if download is not None and any(o.imported_to for o in outcomes):
        download.status = DownloadStatus.IMPORTED.value
        download.message = None
        session.commit()
    request.app.state.events.publish("queue")
    return outcomes
