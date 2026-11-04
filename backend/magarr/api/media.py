from fastapi import APIRouter, status
from pydantic import Field
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.schemas import ApiModel
from magarr.domain import media_settings as service
from magarr.domain.enums import ImportMode
from magarr.domain.models import MediaSettings, RemotePathMapping

router = APIRouter(prefix="/api/v1", tags=["Media management"])


class MediaSettingsResource(ApiModel):
    auto_import: bool
    usenet_import_mode: ImportMode
    torrent_import_mode: ImportMode
    remove_completed_downloads: bool
    recycle_bin: str = Field(max_length=1024)
    file_chmod: str = Field(max_length=4)
    folder_chmod: str = Field(max_length=4)
    chown_user: int | None
    chown_group: int | None

    @classmethod
    def of(cls, row: MediaSettings) -> "MediaSettingsResource":
        return cls(
            auto_import=row.auto_import,
            usenet_import_mode=ImportMode(row.usenet_import_mode),
            torrent_import_mode=ImportMode(row.torrent_import_mode),
            remove_completed_downloads=row.remove_completed_downloads,
            recycle_bin=row.recycle_bin,
            file_chmod=row.file_chmod,
            folder_chmod=row.folder_chmod,
            chown_user=row.chown_user,
            chown_group=row.chown_group,
        )


class MappingResource(ApiModel):
    id: int
    host: str
    remote_path: str
    local_path: str


class MappingBody(ApiModel):
    host: str = Field(min_length=1, max_length=255)
    remote_path: str = Field(min_length=1, max_length=1024)
    local_path: str = Field(min_length=1, max_length=1024)


@router.get("/config/mediamanagement", response_model=MediaSettingsResource)
def get_settings(session: SessionDep) -> MediaSettingsResource:
    row = service.get_media_settings(session)
    session.commit()
    return MediaSettingsResource.of(row)


@router.put("/config/mediamanagement", response_model=MediaSettingsResource)
def save_settings(body: MediaSettingsResource, session: SessionDep) -> MediaSettingsResource:
    values = body.model_dump()
    values["usenet_import_mode"] = body.usenet_import_mode.value
    values["torrent_import_mode"] = body.torrent_import_mode.value
    row = service.update_media_settings(session, values)
    session.commit()
    return MediaSettingsResource.of(row)


@router.get("/remotepathmapping", response_model=list[MappingResource])
def list_mappings(session: SessionDep) -> list[MappingResource]:
    rows = session.scalars(
        select(RemotePathMapping).order_by(RemotePathMapping.host, RemotePathMapping.remote_path)
    )
    return [
        MappingResource(id=m.id, host=m.host, remote_path=m.remote_path, local_path=m.local_path)
        for m in rows
    ]


@router.post(
    "/remotepathmapping", response_model=MappingResource, status_code=status.HTTP_201_CREATED
)
def add_mapping(body: MappingBody, session: SessionDep) -> MappingResource:
    m = service.add_mapping(session, body.host, body.remote_path, body.local_path)
    session.commit()
    return MappingResource(id=m.id, host=m.host, remote_path=m.remote_path, local_path=m.local_path)


@router.delete("/remotepathmapping/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(mapping_id: int, session: SessionDep) -> None:
    service.delete_mapping(session, mapping_id)
    session.commit()
