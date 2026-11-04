"""Transmission client (RPC, https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md)."""

from __future__ import annotations

import base64
from typing import Any, ClassVar

import httpx
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

_SESSION_HEADER = "X-Transmission-Session-Id"
# torrent-get status: 0 stopped, 1 queued to verify, 2 verifying, 3 queued to download,
# 4 downloading, 5 queued to seed, 6 seeding.
_STOPPED, _QUEUED = 0, {1, 2, 3}
_LOCAL_ERROR = 3  # 1 and 2 are tracker warnings/errors: the download itself is fine
_FIELDS = [
    "hashString", "name", "status", "percentDone", "totalSize", "leftUntilDone",
    "downloadDir", "error", "errorString", "labels",
]  # fmt: skip


class TransmissionSettings(ClientSettings):
    port: int = Field(default=9091, ge=1, le=65535)
    url_base: str = Field(default="/transmission", description="Usually /transmission")
    username: str = Field(default="")
    password: str = Field(default="", json_schema_extra={"secret": True})
    directory: str = Field(
        default="", description="Download folder (as Transmission sees it); blank for its default"
    )
    add_paused: bool = Field(default=False, description="Add torrents stopped")


class TransmissionClient(DownloadClient):
    protocol: ClassVar[Protocol] = Protocol.TORRENT
    settings_model: ClassVar[type[ClientSettings]] = TransmissionSettings
    display_name: ClassVar[str] = "Transmission"
    settings: TransmissionSettings

    _session_id: str = ""

    async def _rpc(self, method: str, **arguments: Any) -> dict:
        auth = (
            httpx.BasicAuth(self.settings.username, self.settings.password)
            if self.settings.username
            else None
        )
        body = {"method": method, "arguments": arguments}
        for _ in range(2):  # a 409 hands out the session id; retry once with it
            response = await self._request(
                "POST", "/rpc", json=body, auth=auth, headers={_SESSION_HEADER: self._session_id}
            )
            if response.status_code == 409:
                self._session_id = response.headers.get(_SESSION_HEADER, "")
                continue
            break
        if response.status_code == 401:
            raise DownloadClientError("Transmission rejected the username or password")
        if response.status_code >= 400:
            raise DownloadClientError(f"Transmission returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise DownloadClientError("Transmission did not return JSON; check the URL") from exc
        if data.get("result") != "success":
            raise DownloadClientError(f"Transmission: {data.get('result')}")
        return data.get("arguments") or {}

    async def test(self) -> TestOutcome:
        session = await self._rpc("session-get", fields=["version", "rpc-version"])
        outcome = TestOutcome(version=str(session.get("version", "?")))
        if self.settings.category and int(session.get("rpc-version", 0)) < 16:
            outcome.warnings.append(
                "This Transmission is too old for labels (3.0+), so the category is ignored"
            )
        return outcome

    async def add(self, payload: GrabPayload) -> str:
        arguments: dict[str, Any] = {"paused": self.settings.add_paused}
        if payload.magnet:
            ihash = magnet_hash(payload.magnet)
            if not ihash:
                raise DownloadClientError("Magnet link has no BitTorrent info hash")
            arguments["filename"] = payload.magnet
        else:
            try:
                ihash = info_hash(payload.content)
            except BencodeError as exc:
                raise DownloadClientError(f"Not a valid torrent file: {exc}") from exc
            arguments["metainfo"] = base64.b64encode(payload.content).decode()
        if self.settings.directory:
            arguments["download-dir"] = self.settings.directory
        if self.settings.category:
            arguments["labels"] = [self.settings.category]
        added = await self._rpc("torrent-add", **arguments)
        # "torrent-duplicate": already there (perhaps added by hand); track it all the same.
        torrent = added.get("torrent-added") or added.get("torrent-duplicate") or {}
        return (torrent.get("hashString") or ihash).lower()

    async def items(self, external_ids: set[str]) -> dict[str, ClientItem]:
        if not external_ids:
            return {}
        got = await self._rpc("torrent-get", ids=sorted(external_ids), fields=_FIELDS)
        found: dict[str, ClientItem] = {}
        for torrent in got.get("torrents", []):
            ihash = str(torrent.get("hashString", "")).lower()
            if ihash not in external_ids:
                continue
            done = float(torrent.get("percentDone") or 0)
            state = int(torrent.get("status") or 0)
            message = torrent.get("errorString") or None
            if torrent.get("error") == _LOCAL_ERROR:
                status = ClientItemStatus.FAILED
            elif done >= 1:
                status = ClientItemStatus.COMPLETED
            elif state == _STOPPED:
                status = ClientItemStatus.PAUSED
            elif state in _QUEUED:
                status = ClientItemStatus.QUEUED
            else:
                status = ClientItemStatus.DOWNLOADING
            directory = str(torrent.get("downloadDir") or "").rstrip("/")
            name = torrent.get("name", "")
            labels = torrent.get("labels") or []
            found[ihash] = ClientItem(
                external_id=ihash,
                title=name,
                status=status,
                progress=done,
                size=int(torrent.get("totalSize") or 0),
                size_left=int(torrent.get("leftUntilDone") or 0),
                output_path=f"{directory}/{name}" if directory and name else None,
                message=message,
                category=labels[0] if labels else None,
            )
        return found

    async def remove(self, external_id: str, delete_data: bool) -> None:
        await self._rpc("torrent-remove", ids=[external_id], **{"delete-local-data": delete_data})
