"""Deluge client (Web UI JSON-RPC). Categories use Deluge's Label plugin when it's enabled."""

from __future__ import annotations

import base64
import itertools
from typing import Any, ClassVar

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

_NOT_AUTHENTICATED = 1
_FIELDS = [
    "name",
    "state",
    "progress",
    "total_wanted",
    "total_done",
    "save_path",
    "label",
    "message",
]
_QUEUED = {"Queued", "Checking", "Allocating", "Moving"}


class DelugeSettings(ClientSettings):
    port: int = Field(default=8112, ge=1, le=65535)
    password: str = Field(default="deluge", json_schema_extra={"secret": True})
    directory: str = Field(
        default="", description="Download folder (as Deluge sees it); blank for its default"
    )
    add_paused: bool = Field(default=False, description="Add torrents paused")


class DelugeClient(DownloadClient):
    protocol: ClassVar[Protocol] = Protocol.TORRENT
    settings_model: ClassVar[type[ClientSettings]] = DelugeSettings
    display_name: ClassVar[str] = "Deluge"
    settings: DelugeSettings

    _ids = itertools.count(1)
    _ready: bool = False

    async def _call(self, method: str, *params: Any) -> Any:
        response = await self._request(
            "POST", "/json", json={"method": method, "params": list(params), "id": next(self._ids)}
        )
        if response.status_code >= 400:
            raise DownloadClientError(f"Deluge returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise DownloadClientError("Deluge did not return JSON; check the URL") from exc
        error = data.get("error")
        if error:
            if error.get("code") == _NOT_AUTHENTICATED:
                raise _SessionExpiredError
            raise DownloadClientError(f"Deluge: {error.get('message', error)}")
        return data.get("result")

    async def _connect(self) -> None:
        """Log in to the Web UI and make sure it's connected to a Deluge daemon."""
        if not await self._call("auth.login", self.settings.password):
            raise DownloadClientError("Deluge rejected the password")
        if not await self._call("web.connected"):
            hosts = await self._call("web.get_hosts") or []
            if not hosts:
                raise DownloadClientError("Deluge's Web UI has no daemon to connect to")
            await self._call("web.connect", hosts[0][0])
        self._ready = True

    async def _rpc(self, method: str, *params: Any) -> Any:
        if not self._ready:
            await self._connect()
        try:
            return await self._call(method, *params)
        except _SessionExpiredError:  # session expired
            await self._connect()
            return await self._call(method, *params)

    async def test(self) -> TestOutcome:
        outcome = TestOutcome(version=str(await self._rpc("daemon.get_version")))
        if self.settings.category and not await self._has_labels():
            outcome.warnings.append(
                "Deluge's Label plugin is off, so downloads won't get the category"
            )
        return outcome

    async def _has_labels(self) -> bool:
        return "Label" in (await self._rpc("core.get_enabled_plugins") or [])

    async def add(self, payload: GrabPayload) -> str:
        options: dict[str, Any] = {"add_paused": self.settings.add_paused}
        if self.settings.directory:
            options["download_location"] = self.settings.directory
        if payload.magnet:
            ihash = magnet_hash(payload.magnet)
            if not ihash:
                raise DownloadClientError("Magnet link has no BitTorrent info hash")
            added = await self._rpc("core.add_torrent_magnet", payload.magnet, options)
        else:
            try:
                ihash = info_hash(payload.content)
            except BencodeError as exc:
                raise DownloadClientError(f"Not a valid torrent file: {exc}") from exc
            encoded = base64.b64encode(payload.content).decode()
            added = await self._rpc("core.add_torrent_file", payload.filename, encoded, options)
        if not added:
            raise DownloadClientError("Deluge refused the torrent (already added, or invalid)")
        if self.settings.category and await self._has_labels():
            label = self.settings.category.lower()  # Deluge labels are lower case
            if label not in (await self._rpc("label.get_labels") or []):
                await self._rpc("label.add", label)
            await self._rpc("label.set_torrent", ihash, label)
        return ihash

    async def items(self, external_ids: set[str]) -> dict[str, ClientItem]:
        if not external_ids:
            return {}
        torrents = await self._rpc(
            "core.get_torrents_status", {"id": sorted(external_ids)}, _FIELDS
        )
        found: dict[str, ClientItem] = {}
        for ihash, torrent in (torrents or {}).items():
            ihash = ihash.lower()
            if ihash not in external_ids:
                continue
            progress = float(torrent.get("progress") or 0) / 100
            state = torrent.get("state", "")
            if state == "Error":
                status = ClientItemStatus.FAILED
            elif progress >= 1 or state == "Seeding":
                status = ClientItemStatus.COMPLETED
            elif state == "Paused":
                status = ClientItemStatus.PAUSED
            elif state in _QUEUED:
                status = ClientItemStatus.QUEUED
            else:
                status = ClientItemStatus.DOWNLOADING
            wanted = int(torrent.get("total_wanted") or 0)
            directory = str(torrent.get("save_path") or "").rstrip("/")
            name = torrent.get("name", "")
            message = torrent.get("message")
            found[ihash] = ClientItem(
                external_id=ihash,
                title=name,
                status=status,
                progress=min(progress, 1.0),
                size=wanted,
                size_left=max(wanted - int(torrent.get("total_done") or 0), 0),
                output_path=f"{directory}/{name}" if directory and name else None,
                message=None if message in (None, "", "OK") else message,
                category=torrent.get("label") or None,
            )
        return found

    async def remove(self, external_id: str, delete_data: bool) -> None:
        await self._rpc("core.remove_torrent", external_id, delete_data)


class _SessionExpiredError(Exception):
    pass
