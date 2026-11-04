from fastapi import APIRouter, status
from pydantic import Field
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.schemas import ApiModel
from magarr.domain import root_folders
from magarr.domain.models import RootFolder

router = APIRouter(prefix="/api/v1/rootfolder", tags=["Root folders"])


class RootFolderResource(ApiModel):
    id: int
    path: str
    is_default: bool
    accessible: bool
    free_space: int | None

    @classmethod
    def of(cls, root: RootFolder) -> "RootFolderResource":
        return cls(
            id=root.id,
            path=root.path,
            is_default=root.is_default,
            accessible=root_folders.is_accessible(root.path),
            free_space=root_folders.free_space(root.path),
        )


class RootFolderCreate(ApiModel):
    path: str = Field(min_length=1, max_length=1024)


class RootFolderUpdate(ApiModel):
    is_default: bool


@router.get("", response_model=list[RootFolderResource])
def list_root_folders(session: SessionDep) -> list[RootFolderResource]:
    return [
        RootFolderResource.of(r)
        for r in session.scalars(select(RootFolder).order_by(RootFolder.path))
    ]


@router.post("", response_model=RootFolderResource, status_code=status.HTTP_201_CREATED)
def add_root_folder(body: RootFolderCreate, session: SessionDep) -> RootFolderResource:
    root = root_folders.add_root_folder(session, body.path)
    session.commit()
    return RootFolderResource.of(root)


@router.patch("/{root_id}", response_model=RootFolderResource)
def update_root_folder(
    root_id: int, body: RootFolderUpdate, session: SessionDep
) -> RootFolderResource:
    root = root_folders.get_root_folder(session, root_id)
    if body.is_default:
        root = root_folders.set_default(session, root_id)
    session.commit()
    return RootFolderResource.of(root)


@router.delete("/{root_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_root_folder(root_id: int, session: SessionDep) -> None:
    root_folders.delete_root_folder(session, root_id)
    session.commit()
