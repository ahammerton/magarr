from datetime import datetime

from fastapi import APIRouter, Response
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.paging import PagingDep
from magarr.api.schemas import ApiModel
from magarr.domain.models import RootFolder, UnmappedFile
from magarr.domain.root_folders import get_root_folder
from magarr.importers.library_scan import scan_root_folder

router = APIRouter(prefix="/api/v1/library", tags=["Library"])


class ScanRequest(ApiModel):
    # Omit to scan every root folder.
    root_folder_id: int | None = None


class ScanResultResource(ApiModel):
    root_folder_id: int
    path: str
    files_found: int
    files_added: int
    files_removed: int
    issues_created: int
    magazines_created: int
    unmapped: int


class UnmappedFileResource(ApiModel):
    id: int
    root_folder_id: int
    root_folder_path: str
    relative_path: str
    size: int
    reason: str
    found: datetime


@router.post("/scan", response_model=list[ScanResultResource])
def scan(body: ScanRequest, session: SessionDep) -> list[ScanResultResource]:
    """Reconcile files on disk with the library. Runs synchronously."""
    if body.root_folder_id is not None:
        roots = [get_root_folder(session, body.root_folder_id)]
    else:
        roots = list(session.scalars(select(RootFolder).order_by(RootFolder.path)))
    results = []
    for root in roots:
        results.append(ScanResultResource.model_validate(vars(scan_root_folder(session, root))))
    session.commit()
    return results


@router.get("/unmapped", response_model=list[UnmappedFileResource])
def unmapped(
    session: SessionDep, paging: PagingDep, response: Response
) -> list[UnmappedFileResource]:
    stmt = select(UnmappedFile).order_by(UnmappedFile.root_folder_id, UnmappedFile.relative_path)
    rows = session.scalars(paging.apply(session, stmt, response))
    return [
        UnmappedFileResource(
            id=u.id,
            root_folder_id=u.root_folder_id,
            root_folder_path=u.root_folder.path,
            relative_path=u.relative_path,
            size=u.size,
            reason=u.reason,
            found=u.created_at,
        )
        for u in rows
    ]
