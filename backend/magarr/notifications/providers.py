"""Discord, Slack, generic webhook, ntfy and Pushover."""

from __future__ import annotations

from typing import ClassVar

import httpx
from pydantic import Field

from magarr import APP_NAME
from magarr.core.forms import FormSettings
from magarr.domain.enums import NotificationImplementation
from magarr.notifications.base import Message, NotificationError, Notifier

_URL = r"^https?://\S+$"
# Discord embed colours per event.
_COLOURS = {
    "grab": 0x3B82F6,
    "import": 0x22C55E,
    "upgrade": 0x14B8A6,
    "failure": 0xEF4444,
    "health": 0xF59E0B,
    "test": 0x8B5CF6,
}


class DiscordSettings(FormSettings):
    webhook_url: str = Field(
        # Discord, or a Discord-compatible service: the path is what makes it a webhook.
        pattern=r"^https?://\S+/api/webhooks/\S+$",
        title="Webhook URL",
        description="Channel settings → Integrations → Webhooks → Copy webhook URL",
        json_schema_extra={"secret": True},
    )
    username: str = Field(default=APP_NAME, max_length=80, description="Name shown on messages")


class Discord(Notifier):
    settings_model: ClassVar[type[FormSettings]] = DiscordSettings
    display_name: ClassVar[str] = "Discord"
    settings: DiscordSettings

    async def send(self, message: Message) -> None:
        embed = {"title": message.title[:256], "color": _COLOURS.get(message.event, 0x8B5CF6)}
        if message.body:
            embed["description"] = message.body[:4000]
        await self._post(
            self.settings.webhook_url,
            json={"username": self.settings.username or APP_NAME, "embeds": [embed]},
        )


class SlackSettings(FormSettings):
    webhook_url: str = Field(
        pattern=r"^https://hooks\.slack\.com/\S+$",
        title="Webhook URL",
        description="An incoming webhook from your Slack app",
        json_schema_extra={"secret": True},
    )


class Slack(Notifier):
    settings_model: ClassVar[type[FormSettings]] = SlackSettings
    display_name: ClassVar[str] = "Slack"
    settings: SlackSettings

    async def send(self, message: Message) -> None:
        text = f"*{message.title}*" + (f"\n{message.body}" if message.body else "")
        await self._post(self.settings.webhook_url, json={"text": text})


class WebhookSettings(FormSettings):
    url: str = Field(
        pattern=_URL,
        title="URL",
        description="Receives a JSON POST for each event",
        json_schema_extra={"secret": True},
    )
    username: str = Field(default="", description="Basic auth, if the endpoint needs it")
    password: str = Field(default="", json_schema_extra={"secret": True})


class Webhook(Notifier):
    settings_model: ClassVar[type[FormSettings]] = WebhookSettings
    display_name: ClassVar[str] = "Webhook"
    settings: WebhookSettings

    async def send(self, message: Message) -> None:
        auth = (
            httpx.BasicAuth(self.settings.username, self.settings.password)
            if self.settings.username
            else None
        )
        payload = {
            "app": APP_NAME,
            "event": message.event,
            "title": message.title,
            "message": message.body,
            **{k: v for k, v in message.values.items() if k != "event"},
        }
        await self._post(self.settings.url, json=payload, auth=auth)


class NtfySettings(FormSettings):
    server_url: str = Field(default="https://ntfy.sh", pattern=_URL, title="Server URL")
    topic: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    access_token: str = Field(
        default="", description="For protected topics", json_schema_extra={"secret": True}
    )
    priority: str = Field(
        default="default",
        json_schema_extra={"options": ["min", "low", "default", "high", "max"]},
        pattern=r"^(min|low|default|high|max)$",
    )


class Ntfy(Notifier):
    settings_model: ClassVar[type[FormSettings]] = NtfySettings
    display_name: ClassVar[str] = "ntfy"
    settings: NtfySettings

    async def send(self, message: Message) -> None:
        headers = {
            # Headers must be ASCII; ntfy decodes RFC 2047 for anything else.
            "Title": message.title.encode("ascii", "replace").decode(),
            "Priority": self.settings.priority,
            "Tags": "newspaper",
        }
        if self.settings.access_token:
            headers["Authorization"] = f"Bearer {self.settings.access_token}"
        await self._post(
            f"{self.settings.server_url.rstrip('/')}/{self.settings.topic}",
            content=(message.body or message.title).encode(),
            headers=headers,
        )


_PUSHOVER_PRIORITY = {"lowest": -2, "low": -1, "normal": 0, "high": 1}


class PushoverSettings(FormSettings):
    user_key: str = Field(min_length=1, json_schema_extra={"secret": True})
    api_token: str = Field(
        min_length=1,
        title="API token",
        description="Create an application at pushover.net to get one",
        json_schema_extra={"secret": True},
    )
    device: str = Field(default="", description="Blank sends to all your devices")
    priority: str = Field(
        default="normal",
        json_schema_extra={"options": list(_PUSHOVER_PRIORITY)},
        pattern=r"^(lowest|low|normal|high)$",
    )


class Pushover(Notifier):
    settings_model: ClassVar[type[FormSettings]] = PushoverSettings
    display_name: ClassVar[str] = "Pushover"
    settings: PushoverSettings

    async def send(self, message: Message) -> None:
        data = {
            "token": self.settings.api_token,
            "user": self.settings.user_key,
            "title": message.title[:250],
            "message": (message.body or message.title)[:1024],
            "priority": str(_PUSHOVER_PRIORITY[self.settings.priority]),
        }
        if self.settings.device:
            data["device"] = self.settings.device
        response = await self._post("https://api.pushover.net/1/messages.json", data=data)
        if response.json().get("status") != 1:
            raise NotificationError(f"Pushover refused the message: {response.text[:200]}")


IMPLEMENTATIONS: dict[NotificationImplementation, type[Notifier]] = {
    NotificationImplementation.DISCORD: Discord,
    NotificationImplementation.SLACK: Slack,
    NotificationImplementation.WEBHOOK: Webhook,
    NotificationImplementation.NTFY: Ntfy,
    NotificationImplementation.PUSHOVER: Pushover,
}


def build_notifier(
    implementation: NotificationImplementation, settings: dict, http: httpx.AsyncClient
) -> Notifier:
    cls = IMPLEMENTATIONS[implementation]
    return cls(cls.settings_model.model_validate(settings), http)
