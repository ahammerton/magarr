"""SABnzbd client (https://sabnzbd.org/wiki/configuration/4.3/api)."""

from __future__ import annotations

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

# SABnzbd priorities; "default" (-100) uses the category's priority.
PRIORITIES = {"default": -100, "paused": -2, "low": -1, "normal": 0, "high": 1}

_QUEUE_STATUS = {
    "Downloading": ClientItemStatus.DOWNLOADING,
    "Fetching": ClientItemStatus.DOWNLOADING,
    "Grabbing": ClientItemStatus.QUEUED,
    "Queued": ClientItemStatus.QUEUED,
    "Propagating": ClientItemStatus.QUEUED,
    "Checking": ClientItemStatus.DOWNLOADING,
    "Paused": ClientItemStatus.PAUSED,
}
# History slots in these states are still being processed by SABnzbd.
_POST_PROCESSING = {
    "Queued",
    "QuickCheck",
    "Verifying",
    "Repairing",
    "Fetching",
    "Extracting",
    "Moving",
    "Running",
}


class SabnzbdSettings(ClientSettings):
    port: int = Field(default=8080, ge=1, le=65535)
    api_key: str = Field(min_length=1, title="API key", json_schema_extra={"secret": True})
    priority: str = Field(
        default="default",
        pattern="^(default|paused|low|normal|high)$",
        description="Queue priority for new downloads",
        json_schema_extra={"options": list(PRIORITIES)},
    )


def _mb(value: Any) -> int:
    try:
        return int(float(value) * 1024 * 1024)
    except (TypeError, ValueError):
        return 0


class SabnzbdClient(DownloadClient):
    protocol: ClassVar[Protocol] = Protocol.USENET
    settings_model: ClassVar[type[ClientSettings]] = SabnzbdSettings
    display_name: ClassVar[str] = "SABnzbd"
    settings: SabnzbdSettings

    async def _api(
        self, mode: str, *, method: str = "GET", files: Any = None, **params: str
    ) -> Any:
        query = {"mode": mode, "output": "json", "apikey": self.settings.api_key, **params}
        response = await self._request(method, "/api", params=query, files=files)
        if response.status_code in (401, 403):
            raise DownloadClientError("SABnzbd rejected the API key")
        if response.status_code >= 400:
            raise DownloadClientError(f"SABnzbd returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise DownloadClientError("SABnzbd did not return JSON; check the URL") from exc
        if isinstance(data, dict) and data.get("status") is False:
            raise DownloadClientError(f"SABnzbd: {data.get('error') or 'request failed'}")
        return data

    async def test(self) -> TestOutcome:
        version = (await self._api("version")).get("version", "?")
        # "version" works without a key; get_cats proves the key is accepted.
        categories = (await self._api("get_cats")).get("categories", [])
        outcome = TestOutcome(version=version)
        if self.settings.category and self.settings.category not in categories:
            outcome.warnings.append(
                f"Category '{self.settings.category}' does not exist in SABnzbd, so downloads "
                f"will use its default category. Existing: {', '.join(categories)}"
            )
        queue = (await self._api("queue", limit="0")).get("queue", {})
        if queue.get("paused"):
            outcome.warnings.append("SABnzbd's queue is paused; grabs will wait until it resumes")
        return outcome

    async def add(self, payload: GrabPayload) -> str:
        if not payload.content:
            raise DownloadClientError("No NZB content to send to SABnzbd")
        data = await self._api(
            "addfile",
            method="POST",
            files={"name": (payload.filename, payload.content, "application/x-nzb")},
            nzbname=payload.title,
            cat=self.settings.category or "*",
            priority=str(PRIORITIES[self.settings.priority]),
        )
        ids = data.get("nzo_ids") or []
        if not ids:
            raise DownloadClientError("SABnzbd accepted the request but returned no id")
        return str(ids[0])

    async def items(self, external_ids: set[str]) -> dict[str, ClientItem]:
        if not external_ids:
            return {}
        found: dict[str, ClientItem] = {}
        ids = ",".join(sorted(external_ids))
        queue = (await self._api("queue", nzo_ids=ids)).get("queue", {})
        for slot in queue.get("slots", []):
            if slot.get("nzo_id") not in external_ids:
                continue
            size, left = _mb(slot.get("mb")), _mb(slot.get("mbleft"))
            status = _QUEUE_STATUS.get(slot.get("status", ""), ClientItemStatus.QUEUED)
            if queue.get("paused") and status is not ClientItemStatus.DOWNLOADING:
                status = ClientItemStatus.PAUSED
            found[slot["nzo_id"]] = ClientItem(
                external_id=slot["nzo_id"],
                title=slot.get("filename", ""),
                status=status,
                progress=(1 - left / size) if size else 0.0,
                size=size,
                size_left=left,
                category=slot.get("cat"),
            )
        history = (await self._api("history", nzo_ids=ids)).get("history", {})
        for slot in history.get("slots", []):
            nzo_id = slot.get("nzo_id")
            if nzo_id not in external_ids or nzo_id in found:
                continue
            sab_status = slot.get("status", "")
            size = int(slot.get("bytes") or 0)
            if sab_status == "Completed":
                status, message = ClientItemStatus.COMPLETED, None
            elif sab_status == "Failed":
                status, message = ClientItemStatus.FAILED, slot.get("fail_message") or "Failed"
            else:  # still post-processing
                status, message = ClientItemStatus.DOWNLOADING, f"Post-processing: {sab_status}"
            found[nzo_id] = ClientItem(
                external_id=nzo_id,
                title=slot.get("name", ""),
                status=status,
                progress=1.0 if status is not ClientItemStatus.FAILED else 0.0,
                size=size,
                size_left=0,
                output_path=slot.get("storage") or None,
                message=message,
                category=slot.get("category"),
            )
        return found

    async def remove(self, external_id: str, delete_data: bool) -> None:
        flag = "1" if delete_data else "0"
        await self._api("queue", name="delete", value=external_id, del_files=flag)
        await self._api("history", name="delete", value=external_id, del_files=flag)
