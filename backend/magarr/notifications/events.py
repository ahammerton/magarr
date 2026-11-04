"""Notification events and message templates.

A template's first line is the title; the rest is the body. ``{token}`` is replaced by the
event's value (unknown tokens are left as typed, so a typo is easy to spot).
"""

from __future__ import annotations

import re
from enum import StrEnum

from magarr.domain.enums import HistoryEventType


class NotificationEvent(StrEnum):
    GRAB = "grab"
    IMPORT = "import"
    UPGRADE = "upgrade"
    FAILURE = "failure"
    HEALTH = "health"


# Which history events notify, and as what.
FROM_HISTORY = {
    HistoryEventType.GRABBED: NotificationEvent.GRAB,
    HistoryEventType.IMPORTED: NotificationEvent.IMPORT,
    HistoryEventType.UPGRADED: NotificationEvent.UPGRADE,
    HistoryEventType.DOWNLOAD_FAILED: NotificationEvent.FAILURE,
    HistoryEventType.IMPORT_FAILED: NotificationEvent.FAILURE,
}

TOKENS: dict[str, str] = {
    "magazine": "Magazine title",
    "issue": "Issue number, e.g. 2026-10 or Christmas Special 2026",
    "release": "Release name",
    "quality": "Quality, e.g. pdf_hires",
    "client": "Download client",
    "source": "How it was found: RSS sync, backlog search, manual grab...",
    "path": "Where the file was imported to",
    "message": "Failure reason or health warning",
    "event": "grab, import, upgrade, failure or health",
}

DEFAULT_TEMPLATES: dict[NotificationEvent, str] = {
    NotificationEvent.GRAB: "Grabbed {magazine} {issue}\n{release}\nSent to {client} ({source})",
    NotificationEvent.IMPORT: "Imported {magazine} {issue}\n{path}",
    NotificationEvent.UPGRADE: "Upgraded {magazine} {issue}\n{path}",
    NotificationEvent.FAILURE: "Failed: {magazine} {issue}\n{release}\n{message}",
    NotificationEvent.HEALTH: "Magarr health check\n{message}",
}
TEST_TEMPLATE = "Test from Magarr\nIf you can read this, notifications are working."

_TOKEN = re.compile(r"\{(\w+)\}")


def render(template: str, values: dict[str, object]) -> tuple[str, str]:
    """(title, body) from a template."""

    def value(match: re.Match[str]) -> str:
        name = match[1]
        if name not in TOKENS:
            return match[0]
        found = values.get(name)
        return "" if found is None else str(found)

    text = _TOKEN.sub(value, template)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    title, *body = lines or [""]
    return title or "Magarr", "\n".join(line for line in body if line)
