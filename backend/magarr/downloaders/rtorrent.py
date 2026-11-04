"""rTorrent client (XML-RPC over HTTP, e.g. ruTorrent's /RPC2 or an nginx SCGI proxy).

The category goes in d.custom1, which ruTorrent shows as the label.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any, ClassVar

import httpx
from defusedxml import xmlrpc as defused_xmlrpc
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

# Responses are untrusted XML: parse them with defusedxml's hardened expat.
defused_xmlrpc.monkey_patch()

_FIELDS = (
    "d.hash=", "d.name=", "d.size_bytes=", "d.left_bytes=", "d.complete=", "d.state=",
    "d.is_active=", "d.hashing=", "d.message=", "d.base_path=", "d.directory=", "d.custom1=",
)  # fmt: skip


class RtorrentSettings(ClientSettings):
    port: int = Field(default=8080, ge=1, le=65535)
    url_base: str = Field(default="/RPC2", description="The XML-RPC endpoint, usually /RPC2")
    username: str = Field(default="", description="If the endpoint uses HTTP basic auth")
    password: str = Field(default="", json_schema_extra={"secret": True})
    directory: str = Field(
        default="", description="Download folder (as rTorrent sees it); blank for its default"
    )
    add_paused: bool = Field(default=False, description="Add torrents stopped")


class RtorrentClient(DownloadClient):
    protocol: ClassVar[Protocol] = Protocol.TORRENT
    settings_model: ClassVar[type[ClientSettings]] = RtorrentSettings
    display_name: ClassVar[str] = "rTorrent"
    settings: RtorrentSettings

    async def _call(self, method: str, *params: Any) -> Any:
        auth = (
            httpx.BasicAuth(self.settings.username, self.settings.password)
            if self.settings.username
            else None
        )
        body = xmlrpc.client.dumps(params, method, allow_none=False).encode()
        response = await self._request(
            "POST", "", content=body, auth=auth, headers={"Content-Type": "text/xml"}
        )
        if response.status_code == 401:
            raise DownloadClientError("rTorrent rejected the username or password")
        if response.status_code >= 400:
            raise DownloadClientError(f"rTorrent returned HTTP {response.status_code}")
        try:
            (result,), _ = xmlrpc.client.loads(response.content)
        except xmlrpc.client.Fault as exc:
            raise DownloadClientError(f"rTorrent: {exc.faultString}") from exc
        except Exception as exc:
            raise DownloadClientError("rTorrent did not return XML-RPC; check the URL") from exc
        return result

    def _commands(self) -> list[str]:
        commands = []
        if self.settings.directory:
            commands.append(f"d.directory.set={self.settings.directory}")
        if self.settings.category:
            commands.append(f"d.custom1.set={self.settings.category}")
        return commands

    async def test(self) -> TestOutcome:
        return TestOutcome(version=str(await self._call("system.client_version")))

    async def add(self, payload: GrabPayload) -> str:
        load = "load.start" if not self.settings.add_paused else "load.normal"
        if payload.magnet:
            ihash = magnet_hash(payload.magnet)
            if not ihash:
                raise DownloadClientError("Magnet link has no BitTorrent info hash")
            await self._call(load, "", payload.magnet, *self._commands())
        else:
            try:
                ihash = info_hash(payload.content)
            except BencodeError as exc:
                raise DownloadClientError(f"Not a valid torrent file: {exc}") from exc
            raw = "load.raw_start" if not self.settings.add_paused else "load.raw"
            await self._call(raw, "", xmlrpc.client.Binary(payload.content), *self._commands())
        return ihash

    async def items(self, external_ids: set[str]) -> dict[str, ClientItem]:
        if not external_ids:
            return {}
        rows = await self._call("d.multicall2", "", "main", *_FIELDS)
        found: dict[str, ClientItem] = {}
        for row in rows or []:
            values = dict(zip((f.removesuffix("=") for f in _FIELDS), row, strict=False))
            ihash = str(values["d.hash"]).lower()
            if ihash not in external_ids:
                continue
            size, left = int(values["d.size_bytes"] or 0), int(values["d.left_bytes"] or 0)
            if values["d.complete"]:
                status = ClientItemStatus.COMPLETED
            elif values["d.hashing"]:
                status = ClientItemStatus.QUEUED
            elif not values["d.state"] or not values["d.is_active"]:
                status = ClientItemStatus.PAUSED
            else:
                status = ClientItemStatus.DOWNLOADING
            path = values["d.base_path"] or (
                f"{str(values['d.directory']).rstrip('/')}/{values['d.name']}"
                if values["d.directory"]
                else None
            )
            found[ihash] = ClientItem(
                external_id=ihash,
                title=values["d.name"],
                status=status,
                progress=(1 - left / size) if size else 0.0,
                size=size,
                size_left=left,
                output_path=path or None,
                message=values["d.message"] or None,
                category=values["d.custom1"] or None,
            )
        return found

    async def remove(self, external_id: str, delete_data: bool) -> None:
        ihash = external_id.upper()
        if delete_data:
            # rTorrent never deletes files itself; ruTorrent's erasedata plugin does when this
            # is set before the erase.
            await self._call("d.custom5.set", ihash, "1")
        await self._call("d.erase", ihash)
