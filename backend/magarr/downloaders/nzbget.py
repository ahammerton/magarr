"""NZBGet client (JSON-RPC API, https://nzbget.com/documentation/api/)."""

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

PRIORITIES = {"very low": -100, "low": -50, "normal": 0, "high": 50, "very high": 100}

# Queue statuses: everything from PP_QUEUED onwards is post-processing.
_QUEUED = {"QUEUED", "LOADING_PARS"}
_DOWNLOADING = {"DOWNLOADING", "FETCHING"}
_PAUSED = {"PAUSED"}
# History Status is "<KIND>/<DETAIL>": SUCCESS/ALL, SUCCESS/UNPACK, FAILURE/PAR, WARNING/SCRIPT...
_HISTORY_OK = {"SUCCESS"}


class NzbgetSettings(ClientSettings):
    port: int = Field(default=6789, ge=1, le=65535)
    username: str = Field(default="nzbget")
    password: str = Field(default="", json_schema_extra={"secret": True})
    priority: str = Field(
        default="normal",
        pattern="^(very low|low|normal|high|very high)$",
        description="Queue priority for new downloads",
        json_schema_extra={"options": list(PRIORITIES)},
    )


def _mb(item: dict, key: str) -> int:
    try:
        return int(float(item.get(f"{key}MB", 0)) * 1024 * 1024)
    except (TypeError, ValueError):
        return 0


class NzbgetClient(DownloadClient):
    protocol: ClassVar[Protocol] = Protocol.USENET
    settings_model: ClassVar[type[ClientSettings]] = NzbgetSettings
    display_name: ClassVar[str] = "NZBGet"
    settings: NzbgetSettings

    async def _rpc(self, method: str, *params: Any) -> Any:
        response = await self._request(
            "POST",
            "/jsonrpc",
            json={"version": "1.1", "method": method, "params": list(params)},
            auth=httpx.BasicAuth(self.settings.username, self.settings.password),
        )
        if response.status_code == 401:
            raise DownloadClientError("NZBGet rejected the username or password")
        if response.status_code >= 400:
            raise DownloadClientError(f"NZBGet returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise DownloadClientError("NZBGet did not return JSON; check the URL") from exc
        if data.get("error"):
            error = data["error"]
            raise DownloadClientError(
                f"NZBGet: {error.get('message', error) if isinstance(error, dict) else error}"
            )
        return data.get("result")

    async def test(self) -> TestOutcome:
        version = str(await self._rpc("version"))
        outcome = TestOutcome(version=version)
        config = {c.get("Name"): c.get("Value") for c in await self._rpc("config") or []}
        categories = [
            v for k, v in config.items() if k and k.startswith("Category") and k.endswith(".Name")
        ]
        if self.settings.category and self.settings.category not in categories:
            outcome.warnings.append(
                f"Category '{self.settings.category}' does not exist in NZBGet, so downloads will "
                f"go to its default folder. Existing: {', '.join(categories) or 'none'}"
            )
        return outcome

    async def add(self, payload: GrabPayload) -> str:
        if not payload.content:
            raise DownloadClientError("No NZB content to send to NZBGet")
        nzb_id = await self._rpc(
            "append",
            payload.filename,
            base64.b64encode(payload.content).decode(),
            self.settings.category,
            PRIORITIES[self.settings.priority],
            False,  # AddToTop
            False,  # AddPaused
            "",  # DupeKey
            0,  # DupeScore
            "SCORE",  # DupeMode
            [],  # PPParameters
        )
        if not isinstance(nzb_id, int) or nzb_id <= 0:
            raise DownloadClientError("NZBGet refused the NZB")
        return str(nzb_id)

    async def items(self, external_ids: set[str]) -> dict[str, ClientItem]:
        if not external_ids:
            return {}
        found: dict[str, ClientItem] = {}
        for group in await self._rpc("listgroups", 0) or []:
            nzb_id = str(group.get("NZBID"))
            if nzb_id not in external_ids:
                continue
            status = group.get("Status", "")
            size, left = _mb(group, "FileSize"), _mb(group, "RemainingSize")
            if status in _PAUSED:
                state, message = ClientItemStatus.PAUSED, None
            elif status in _QUEUED:
                state, message = ClientItemStatus.QUEUED, None
            elif status in _DOWNLOADING:
                state, message = ClientItemStatus.DOWNLOADING, None
            else:
                state, message = ClientItemStatus.DOWNLOADING, f"Post-processing: {status.lower()}"
            found[nzb_id] = ClientItem(
                external_id=nzb_id,
                title=group.get("NZBName", ""),
                status=state,
                progress=(1 - left / size) if size else 0.0,
                size=size,
                size_left=left,
                message=message,
                category=group.get("Category"),
            )
        for entry in await self._rpc("history", False) or []:
            nzb_id = str(entry.get("NZBID"))
            if nzb_id not in external_ids or nzb_id in found:
                continue
            kind, _, detail = (entry.get("Status") or "").partition("/")
            if entry.get("DeleteStatus") not in (None, "", "NONE") or kind == "DELETED":
                state, message = (
                    ClientItemStatus.FAILED,
                    f"Deleted in NZBGet ({entry.get('DeleteStatus') or detail})",
                )
            elif kind in _HISTORY_OK:
                state, message = ClientItemStatus.COMPLETED, None
            else:  # FAILURE/... or WARNING/...: NZBGet could not produce a good result
                state, message = ClientItemStatus.FAILED, f"NZBGet: {entry.get('Status')}"
            found[nzb_id] = ClientItem(
                external_id=nzb_id,
                title=entry.get("Name", ""),
                status=state,
                progress=1.0 if state is ClientItemStatus.COMPLETED else 0.0,
                size=_mb(entry, "FileSize"),
                size_left=0,
                output_path=entry.get("FinalDir") or entry.get("DestDir") or None,
                message=message,
                category=entry.get("Category"),
            )
        return found

    async def remove(self, external_id: str, delete_data: bool) -> None:
        ids = [int(external_id)]
        await self._rpc("editqueue", "GroupFinalDelete" if delete_data else "GroupDelete", "", ids)
        await self._rpc(
            "editqueue", "HistoryFinalDelete" if delete_data else "HistoryDelete", "", ids
        )
