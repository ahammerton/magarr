"""Send notifications in the background, after the change that caused them is committed.

``history.record`` queues an event on the session; it is only handed to the dispatcher when the
session commits (a rolled-back grab never says "Grabbed"). ``notify`` sends straight away (health
warnings). Both are safe to call from worker threads (sync API endpoints).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from magarr.core.logging import redact
from magarr.domain.enums import NotificationImplementation
from magarr.domain.models import Notification
from magarr.notifications.base import Message, NotificationError
from magarr.notifications.events import DEFAULT_TEMPLATES, NotificationEvent, render
from magarr.notifications.providers import build_notifier

logger = logging.getLogger(__name__)

_PENDING = "magarr_notifications"
_dispatcher: Dispatcher | None = None


def message_for(row: Notification, kind: NotificationEvent, values: dict[str, object]) -> Message:
    template = (row.templates or {}).get(kind.value) or DEFAULT_TEMPLATES[kind]
    title, body = render(template, {**values, "event": kind.value})
    return Message(event=kind.value, title=title, body=body, values=values)


class Dispatcher:
    def __init__(self, session_factory: sessionmaker[Session], http: httpx.AsyncClient) -> None:
        self.session_factory = session_factory
        self.http = http
        self.queue: asyncio.Queue[tuple[NotificationEvent, dict[str, object]]] = asyncio.Queue()
        self.loop = asyncio.get_running_loop()

    def submit(self, kind: NotificationEvent, values: dict[str, object]) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.queue.put_nowait((kind, values))
        else:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, (kind, values))

    async def send_one(self, row: Notification, message: Message) -> str | None:
        """Send to one connection; returns the error, if any (also stored on the row)."""
        notifier = build_notifier(
            NotificationImplementation(row.implementation), row.settings, self.http
        )
        try:
            await notifier.send(message)
        except NotificationError as exc:
            row.last_error = redact(str(exc))[:1024]
            logger.warning(
                "Notification failed", extra={"notification": row.name, "error": row.last_error}
            )
            return row.last_error
        row.last_error, row.last_sent = None, datetime.now(UTC)
        return None

    async def deliver(self, kind: NotificationEvent, values: dict[str, object]) -> None:
        with self.session_factory() as session:
            rows = [
                row
                for row in session.scalars(
                    select(Notification).where(Notification.enabled.is_(True))
                )
                if kind.value in (row.events or [])
            ]
            for row in rows:
                await self.send_one(row, message_for(row, kind, values))
            session.commit()

    async def run(self) -> None:
        while True:
            kind, values = await self.queue.get()
            try:
                await self.deliver(kind, values)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sending notifications crashed", extra={"event": kind.value})


def install(dispatcher: Dispatcher | None) -> None:
    global _dispatcher
    _dispatcher = dispatcher


def notify(kind: NotificationEvent, **values: object) -> None:
    """Send now (no transaction involved)."""
    if _dispatcher is not None:
        _dispatcher.submit(kind, values)


def notify_on_commit(session: Session, kind: NotificationEvent, **values: object) -> None:
    session.info.setdefault(_PENDING, []).append((kind, values))


@event.listens_for(Session, "after_commit")
def _send_pending(session: Session) -> None:
    for kind, values in session.info.pop(_PENDING, []):
        notify(kind, **values)


@event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING, None)
