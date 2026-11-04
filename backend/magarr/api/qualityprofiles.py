from typing import Annotated

from fastapi import APIRouter, status
from pydantic import Field, StringConstraints
from sqlalchemy import select

from magarr.api.deps import SessionDep
from magarr.api.schemas import ApiModel, ShortText
from magarr.domain import profiles
from magarr.domain.models import QualityProfile
from magarr.domain.profiles import ProfileItemSpec, ProfileRules
from magarr.domain.qualities import QUALITIES

router = APIRouter(prefix="/api/v1", tags=["Quality profiles"])


class QualityResource(ApiModel):
    id: str
    name: str
    formats: list[str]


class ProfileItem(ApiModel):
    quality: str = Field(max_length=32)
    allowed: bool = True
    max_size_mb: int | None = Field(default=None, ge=0, le=1_000_000)
    upgrade_until: bool = False


class QualityProfileResource(ApiModel):
    id: int
    name: str
    items: list[ProfileItem]
    protocols: list[str]
    must_contain: list[str]
    must_not_contain: list[str]

    @classmethod
    def of(cls, profile: QualityProfile) -> "QualityProfileResource":
        return cls(
            id=profile.id,
            name=profile.name,
            protocols=profile.protocols or ["usenet", "torrent"],
            must_contain=profile.must_contain or [],
            must_not_contain=profile.must_not_contain or [],
            items=[
                ProfileItem(
                    quality=i.quality,
                    allowed=i.allowed,
                    max_size_mb=i.max_size_mb,
                    upgrade_until=i.upgrade_until,
                )
                for i in profile.items
            ],
        )


class QualityProfileBody(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    # Most-preferred first. Omitted qualities are added as not allowed.
    items: list[ProfileItem] = Field(max_length=50)
    protocols: list[Annotated[str, StringConstraints(max_length=16)]] = Field(
        default_factory=lambda: ["usenet", "torrent"], max_length=2
    )
    # Plain text (case-insensitive) or /regex/.
    must_contain: list[ShortText] = Field(default_factory=list, max_length=100)
    must_not_contain: list[ShortText] = Field(default_factory=list, max_length=100)

    def rules(self) -> ProfileRules:
        return ProfileRules(
            tuple(self.protocols), tuple(self.must_contain), tuple(self.must_not_contain)
        )


def _specs(body: QualityProfileBody) -> list[ProfileItemSpec]:
    return [
        ProfileItemSpec(i.quality, i.allowed, i.max_size_mb, i.upgrade_until) for i in body.items
    ]


@router.get("/quality", response_model=list[QualityResource], tags=["Quality profiles"])
def list_qualities() -> list[QualityResource]:
    return [
        QualityResource(id=q.id, name=q.name, formats=[f.value for f in q.formats])
        for q in QUALITIES
    ]


@router.get("/qualityprofile", response_model=list[QualityProfileResource])
def list_profiles(session: SessionDep) -> list[QualityProfileResource]:
    rows = session.scalars(select(QualityProfile).order_by(QualityProfile.name))
    return [QualityProfileResource.of(p) for p in rows]


@router.get("/qualityprofile/{profile_id}", response_model=QualityProfileResource)
def get_profile(profile_id: int, session: SessionDep) -> QualityProfileResource:
    return QualityProfileResource.of(profiles.get_profile(session, profile_id))


@router.post(
    "/qualityprofile", response_model=QualityProfileResource, status_code=status.HTTP_201_CREATED
)
def create_profile(body: QualityProfileBody, session: SessionDep) -> QualityProfileResource:
    profile = profiles.create_profile(session, body.name, _specs(body), body.rules())
    session.commit()
    return QualityProfileResource.of(profile)


@router.put("/qualityprofile/{profile_id}", response_model=QualityProfileResource)
def update_profile(
    profile_id: int, body: QualityProfileBody, session: SessionDep
) -> QualityProfileResource:
    profile = profiles.update_profile(session, profile_id, body.name, _specs(body), body.rules())
    session.commit()
    return QualityProfileResource.of(profile)


@router.delete("/qualityprofile/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: int, session: SessionDep) -> None:
    profiles.delete_profile(session, profile_id)
    session.commit()
