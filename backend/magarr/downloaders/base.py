"""Download client interface. New clients are additive: subclass DownloadClient and register it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

import httpx
from pydantic import Field

from magarr.core.forms import FormSettings
from magarr.domain.enums import Protocol


class DownloadClientError(Exception):
    """The client could not be reached, rejected us, or refused the item."""


class ClientItemStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ClientItem:
    external_id: str
    title: str
    status: ClientItemStatus
    progress: float  # 0..1
    size: int
    size_left: int
    output_path: str | None = None
    message: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class GrabPayload:
    """What gets sent to the client: the release file itself, fetched by Magarr."""

    title: str
    filename: str
    content: bytes = b""
    magnet: str | None = None  # torrents only, when the indexer gives a magnet link


@dataclass
class TestOutcome:
    version: str
    warnings: list[str] = field(default_factory=list)


class ClientSettings(FormSettings):
    """Fields every client has. Secret fields are marked with json_schema_extra={"secret": True}."""

    host: str = Field(min_length=1, description="Hostname or IP address")
    port: int = Field(ge=1, le=65535)
    use_ssl: bool = Field(default=False, title="Use SSL")
    url_base: str = Field(default="", description="For reverse proxies, e.g. /sabnzbd")
    category: str = Field(default="magazines", description="Category Magarr adds downloads to")

    def base_url(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        base = "/" + self.url_base.strip("/") if self.url_base.strip("/") else ""
        return f"{scheme}://{self.host.strip()}:{self.port}{base}"


class DownloadClient(ABC):
    protocol: ClassVar[Protocol]
    settings_model: ClassVar[type[ClientSettings]]
    display_name: ClassVar[str]

    def __init__(self, settings: ClientSettings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http

    @abstractmethod
    async def test(self) -> TestOutcome:
        """Check connectivity and credentials; return the client version and any warnings."""

    @abstractmethod
    async def add(self, payload: GrabPayload) -> str:
        """Send a release to the client and return its id for the item."""

    @abstractmethod
    async def items(self, external_ids: set[str]) -> dict[str, ClientItem]:
        """Current state of the given items; ids the client no longer knows are omitted."""

    @abstractmethod
    async def remove(self, external_id: str, delete_data: bool) -> None:
        """Remove the item from the client (and optionally its downloaded data)."""

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = self.settings.base_url() + path
        try:
            response = await self.http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise DownloadClientError(f"Timed out talking to {self.display_name}") from exc
        except httpx.HTTPError as exc:
            raise DownloadClientError(f"Could not reach {self.display_name}: {exc}") from exc
        return response
