"""qBittorrent client (WebUI API v2)."""

from __future__ import annotations

import contextlib
from typing import ClassVar

from pydantic import Field

from magarr.domain.enums import Protocol
from magarr.downloaders.base import (
    ClientItem,
    ClientItemStatus,
    ClientSettings,
    DownloadClient,
    DownloadClientError,
    GrabPayload,
    TestOutcome,
)
from magarr.downloaders.bencode import BencodeError, info_hash, magnet_hash

_DOWNLOADING = {
    "downloading",
    "metaDL",
    "forcedDL",
    "stalledDL",
    "checkingDL",
    "allocating",
    "forcedMetaDL",
}
_QUEUED = {"queuedDL", "checkingResumeData", "moving"}
_PAUSED = {"pausedDL", "stoppedDL"}
_FAILED = {"error", "missingFiles"}
# Anything else (uploading, stalledUP, pausedUP, stoppedUP, queuedUP, forcedUP, checkingUP) is
# fully downloaded.


class QbittorrentSettings(ClientSettings):
    port: int = Field(default=8080, ge=1, le=65535)
    username: str = Field(default="admin")
    password: str = Field(default="", json_schema_extra={"secret": True})
    add_paused: bool = Field(default=False, description="Add torrents stopped")


class QbittorrentClient(DownloadClient):
    protocol: ClassVar[Protocol] = Protocol.TORRENT
    settings_model: ClassVar[type[ClientSettings]] = QbittorrentSettings
    display_name: ClassVar[str] = "qBittorrent"
    settings: QbittorrentSettings

    _logged_in: bool = False

    async def _login(self) -> None:
        response = await self._request(
            "POST",
            "/api/v2/auth/login",
            data={"username": self.settings.username, "password": self.settings.password},
            # qBittorrent's CSRF check compares Referer/Origin with its own address.
            headers={"Referer": self.settings.base_url()},
        )
        if response.status_code == 403:
            raise DownloadClientError("qBittorrent banned this address after failed logins")
        if response.status_code >= 400 or response.text.strip() != "Ok.":
            raise DownloadClientError("qBittorrent rejected the username or password")
        self._logged_in = True

    async def _call(self, method: str, path: str, **kwargs):
        if not self._logged_in:
            await self._login()
        headers = {"Referer": self.settings.base_url(), **kwargs.pop("headers", {})}
        response = await self._request(method, path, headers=headers, **kwargs)
        if response.status_code == 403:  # session expired
            await self._login()
            response = await self._request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise DownloadClientError(
                f"qBittorrent returned HTTP {response.status_code} for {path}"
            )
        return response

    async def test(self) -> TestOutcome:
        version = (await self._call("GET", "/api/v2/app/version")).text.strip()
        return TestOutcome(version=version)

    async def add(self, payload: GrabPayload) -> str:
        if payload.magnet:
            ihash = magnet_hash(payload.magnet)
            if not ihash:
                raise DownloadClientError("Magnet link has no BitTorrent info hash")
            files, data = None, {"urls": payload.magnet}
        else:
            try:
                ihash = info_hash(payload.content)
            except BencodeError as exc:
                raise DownloadClientError(f"Not a valid torrent file: {exc}") from exc
            files, data = (
                {"torrents": (payload.filename, payload.content, "application/x-bittorrent")},
                {},
            )
        if self.settings.category:
            # Creating an existing category returns 409, which is fine.
            with contextlib.suppress(DownloadClientError):
                await self._call(
                    "POST",
                    "/api/v2/torrents/createCategory",
                    data={"category": self.settings.category},
                )
            data["category"] = self.settings.category
        if self.settings.add_paused:
            data["paused"] = data["stopped"] = "true"  # qBittorrent 4.x / 5.x names
        response = await self._call("POST", "/api/v2/torrents/add", data=data, files=files)
        if response.text.strip() == "Fails.":
            raise DownloadClientError("qBittorrent refused the torrent (already added, or invalid)")
        return ihash

    async def items(self, external_ids: set[str]) -> dict[str, ClientItem]:
        if not external_ids:
            return {}
        response = await self._call(
            "GET", "/api/v2/torrents/info", params={"hashes": "|".join(sorted(external_ids))}
        )
        found: dict[str, ClientItem] = {}
        for torrent in response.json():
            ihash = torrent.get("hash", "").lower()
            if ihash not in external_ids:
                continue
            state = torrent.get("state", "")
            progress = float(torrent.get("progress") or 0)
            if state in _FAILED:
                status, message = ClientItemStatus.FAILED, f"qBittorrent state: {state}"
            elif state in _PAUSED and progress < 1:
                status, message = ClientItemStatus.PAUSED, None
            elif state in _DOWNLOADING and progress < 1:
                status, message = ClientItemStatus.DOWNLOADING, None
            elif state in _QUEUED and progress < 1:
                status, message = ClientItemStatus.QUEUED, None
            else:
                status, message = ClientItemStatus.COMPLETED, None
            size = int(torrent.get("size") or 0)
            found[ihash] = ClientItem(
                external_id=ihash,
                title=torrent.get("name", ""),
                status=status,
                progress=progress,
                size=size,
                size_left=int(torrent.get("amount_left") or 0),
                output_path=torrent.get("content_path") or None,
                message=message,
                category=torrent.get("category"),
            )
        return found

    async def remove(self, external_id: str, delete_data: bool) -> None:
        await self._call(
            "POST",
            "/api/v2/torrents/delete",
            data={"hashes": external_id, "deleteFiles": "true" if delete_data else "false"},
        )
