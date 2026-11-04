"""Notification sender interface. New services are additive: subclass Notifier and register it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

import httpx

from magarr.core.forms import FormSettings
from magarr.core.logging import redact


class NotificationError(Exception):
    """The service could not be reached or refused the message."""


@dataclass(frozen=True)
class Message:
    event: str  # a NotificationEvent value, or "test"
    title: str
    body: str
    values: dict[str, object] = field(default_factory=dict)


class Notifier(ABC):
    settings_model: ClassVar[type[FormSettings]]
    display_name: ClassVar[str]

    def __init__(self, settings: FormSettings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http

    @abstractmethod
    async def send(self, message: Message) -> None:
        """Deliver the message; raise NotificationError on failure."""

    async def _post(self, url: str, **kwargs) -> httpx.Response:
        try:
            # No redirects: a webhook mustn't be able to send Magarr somewhere else.
            response = await self.http.post(url, timeout=15, follow_redirects=False, **kwargs)
        except httpx.HTTPError as exc:
            raise NotificationError(
                f"Could not reach {self.display_name}: {redact(str(exc))}"
            ) from exc
        if response.status_code >= 400:
            detail = response.text.strip()[:200]
            raise NotificationError(
                f"{self.display_name} returned HTTP {response.status_code}"
                + (f": {redact(detail)}" if detail else "")
            )
        return response
