from dataclasses import asdict
from datetime import date

from fastapi import APIRouter
from pydantic import Field

from magarr.api.deps import SessionDep
from magarr.api.schemas import ApiModel
from magarr.domain import naming_config
from magarr.domain.naming import (
    ISSUE_FILE_TOKENS,
    MAGAZINE_FOLDER_TOKENS,
    YEAR_FOLDER_TOKENS,
    IssueNamingInput,
    NamingScheme,
    issue_relative_path,
    magazine_folder_name,
    validate_scheme,
)

router = APIRouter(prefix="/api/v1/config/naming", tags=["Naming"])


class NamingConfigResource(ApiModel):
    magazine_folder_pattern: str = Field(max_length=255)
    year_folder_pattern: str = Field(max_length=255)
    issue_file_pattern: str = Field(max_length=255)
    replace_illegal_characters: bool
    colon_replacement: str = Field(max_length=10)

    def scheme(self) -> NamingScheme:
        return NamingScheme(**self.model_dump())

    @classmethod
    def of(cls, scheme: NamingScheme) -> "NamingConfigResource":
        return cls(**asdict(scheme))


class NamingTokens(ApiModel):
    magazine_folder: list[str]
    year_folder: list[str]
    issue_file: list[str]


class NamingPreview(ApiModel):
    magazine_folder: str
    issue_path: str
    tokens: NamingTokens


_SAMPLE = IssueNamingInput(
    magazine_title="National Geographic",
    first_issue_year=1888,
    publisher="National Geographic Partners",
    issue_number="045",
    issue_title="The Ocean Issue",
    publish_date=date(2014, 7, 1),
    format="pdf",
    quality="PDF",
)


@router.get("", response_model=NamingConfigResource)
def get_naming(session: SessionDep) -> NamingConfigResource:
    return NamingConfigResource.of(naming_config.get_scheme(session))


@router.put("", response_model=NamingConfigResource)
def update_naming(body: NamingConfigResource, session: SessionDep) -> NamingConfigResource:
    scheme = naming_config.update_scheme(session, body.scheme())
    session.commit()
    return NamingConfigResource.of(scheme)


@router.post("/preview", response_model=NamingPreview)
def preview_naming(body: NamingConfigResource) -> NamingPreview:
    """Render a sample issue with unsaved settings."""
    scheme = body.scheme()
    validate_scheme(scheme)
    folder = magazine_folder_name(
        _SAMPLE.magazine_title, _SAMPLE.first_issue_year, _SAMPLE.publisher, scheme
    )
    return NamingPreview(
        magazine_folder=folder,
        issue_path=f"{folder}/{issue_relative_path(_SAMPLE, scheme)}",
        tokens=NamingTokens(
            magazine_folder=sorted(MAGAZINE_FOLDER_TOKENS),
            year_folder=sorted(YEAR_FOLDER_TOKENS),
            issue_file=sorted(ISSUE_FILE_TOKENS),
        ),
    )
